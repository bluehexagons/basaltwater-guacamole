#!/usr/bin/env python3
"""Build and check pinned RDP/SSH Guacamole packages for Debian Trixie."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
SPEC = json.loads((ROOT / "release.json").read_text())
PACKAGE = "basaltwater-guacamole"
PREFIX = Path("/opt/basaltwater-guacamole") / SPEC["build_version"]
BUILD_PACKAGES = (
    "build-essential", "pkg-config", "dpkg-dev", "python3",
    "libcairo2-dev", "libjpeg62-turbo-dev", "libpng-dev", "uuid-dev",
    "libssl-dev", "freerdp3-dev", "libwebp-dev", "libssh2-1-dev", "libpango1.0-dev",
)


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
    if result.returncode:
        raise RuntimeError(f"Command failed: {args!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def architecture() -> str:
    arch = run("dpkg", "--print-architecture")
    if arch != "amd64":
        raise RuntimeError(f"Unsupported architecture: {arch}")
    return arch


def filename(arch: str) -> str:
    return f"{PACKAGE}_{SPEC['package_version']}_trixie_{arch}.deb"


def download_source(component: str, target: Path) -> None:
    version = SPEC["upstream_version"]
    name = f"guacamole-{component}-{version}.tar.gz"
    for base in ("https://dlcdn.apache.org/guacamole",
                 "https://archive.apache.org/dist/guacamole"):
        digest = hashlib.sha256()
        deadline = time.monotonic() + 600
        try:
            with urllib.request.urlopen(f"{base}/{version}/source/{name}", timeout=30) as response, target.open("wb") as output:
                size = 0
                while chunk := response.read1(1024 * 1024):
                    size += len(chunk)
                    if size > 32 * 1024 * 1024 or time.monotonic() > deadline:
                        raise RuntimeError("Source download exceeded its bounds")
                    digest.update(chunk)
                    output.write(chunk)
            break
        except OSError:
            if "archive.apache.org" in base:
                raise
    if digest.hexdigest() != SPEC["sources"][component]:
        raise RuntimeError(f"Invalid checksum for {name}")


def extract_source(archive: Path, destination: Path) -> None:
    count = total = 0
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            count += 1
            total += member.size
            path = PurePosixPath(member.name)
            if (count > 10000 or total > 128 * 1024 * 1024
                    or path.is_absolute() or ".." in path.parts
                    or not (member.isdir() or member.isfile())):
                raise RuntimeError("Unsafe source archive")
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as input_file, target.open("xb") as output:
                    shutil.copyfileobj(input_file, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
                os.utime(target, (member.mtime, member.mtime))


def dependencies(work: Path, release: Path) -> str:
    debian = work / "debian"
    debian.mkdir()
    (debian / "control").write_text(
        f"Source: {PACKAGE}\n\nPackage: {PACKAGE}\nArchitecture: any\n"
        "Description: Basaltwater Guacamole runtime\n"
    )
    binaries = [release / "sbin/guacd"]
    binaries.extend(path for path in (release / "lib").rglob("*.so*")
                    if path.is_file() and not path.is_symlink())
    shlibs = []
    for path in binaries:
        match = re.search(r"\(SONAME\).*\[(.+)\]", run("readelf", "-d", str(path)))
        if match and ".so." in match[1]:
            name, major = match[1].rsplit(".so.", 1)
            shlibs.append(f"{name} {major} {PACKAGE}")
    local = debian / "shlibs.local"
    local.write_text("\n".join(shlibs) + "\n")
    result = run("dpkg-shlibdeps", "-O", f"-l{release / 'lib'}",
                 f"-L{local}", f"-x{PACKAGE}",
                 *(f"-e{path}" for path in binaries), cwd=work)
    depends = result.removeprefix("shlibs:Depends=")
    if not result.startswith("shlibs:Depends=") or not depends or "\n" in depends:
        raise RuntimeError(f"Unexpected dependency metadata: {result}")
    return depends


def build() -> None:
    if "VERSION_CODENAME=trixie" not in Path("/etc/os-release").read_text():
        raise RuntimeError("Build inside Debian Trixie")
    arch = architecture()
    with tempfile.TemporaryDirectory(prefix="guacamole-build-") as directory:
        work = Path(directory)
        for component in ("server", "client"):
            archive = work / f"{component}.tar.gz"
            download_source(component, archive)
            extract_source(archive, work)
        server = work / f"guacamole-server-{SPEC['upstream_version']}"
        stage = work / "stage"
        release = stage / PREFIX.relative_to("/")
        print(f"Compiling Guacamole for {arch}", flush=True)
        run("./configure", f"--prefix={PREFIX}", "--with-rdp",
            "--without-vnc", "--with-ssh", "--without-telnet", "--with-terminal",
            "--without-pulse", "--without-vorbis", "--without-libavcodec",
            "--without-libavformat", "--without-libavutil", "--without-libswscale",
            "--disable-kubernetes", "--disable-guacenc", "--disable-guaclog",
            f"--with-freerdp-plugin-dir={PREFIX}/lib/freerdp3",
            "CFLAGS=-O2 -Wno-error=deprecated-declarations", cwd=server)
        run("make", "-j2", cwd=server)
        run("make", "install", f"DESTDIR={stage}", cwd=server)
        for protocol in ("rdp", "ssh"):
            if not (release / f"lib/libguac-client-{protocol}.so").is_file():
                raise RuntimeError(f"{protocol.upper()} support was not built")
        shutil.rmtree(release / "include")
        if (release / "lib/pkgconfig").exists():
            shutil.rmtree(release / "lib/pkgconfig")
        for path in release.rglob("*"):
            if path.suffix in {".a", ".la"}:
                path.unlink()
        client = work / f"guacamole-client-{SPEC['upstream_version']}"
        modules = client / "guacamole-common-js/src/main/webapp/modules"
        ordered = [modules / "Namespace.js"]
        ordered.extend(path for path in sorted(modules.glob("*.js"))
                       if path.name != "Namespace.js")
        share = release / "share"
        share.mkdir(exist_ok=True)
        license_js = client / "guacamole-common-js/src/main/webapp/common/license.js"
        (share / "all.js").write_bytes(
            b"\n".join(path.read_bytes() for path in [license_js, *ordered]) + b"\n")
        for component, source in (("server", server), ("client", client)):
            for name in ("LICENSE", "NOTICE"):
                shutil.copyfile(source / name, share / f"{name}.{component}")
        depends = dependencies(work, release) + ", fonts-dejavu-core"
        metadata = {**SPEC, "architecture": arch, "distribution": "trixie",
                    "dependencies": depends,
                    "build_commit": os.environ.get("GUACAMOLE_BUILD_COMMIT", "local")}
        (release / ".basaltwater-release.json").write_text(
            json.dumps(metadata, sort_keys=True) + "\n")
        control = stage / "DEBIAN"
        control.mkdir()
        (control / "control").write_text(
            f"Package: {PACKAGE}\nVersion: {SPEC['package_version']}\n"
            f"Architecture: {arch}\nSection: net\nPriority: optional\n"
            "Maintainer: Basaltwater <maintainers@basaltwater.invalid>\n"
            f"Depends: {depends}\n"
            "Homepage: https://github.com/bluehexagons/basaltwater-guacamole\n"
            "Description: RDP and SSH Guacamole runtime for Basaltwater\n"
            " Native guacd and JavaScript client; services are managed by Basaltwater.\n"
        )
        for path in [release / "sbin/guacd", *(release / "lib").rglob("*.so*")]:
            if path.is_file() and not path.is_symlink():
                run("strip", "--strip-unneeded", str(path))
        output = ROOT / "dist"
        output.mkdir(exist_ok=True)
        package = output / filename(arch)
        run("dpkg-deb", "--root-owner-group", "--build", str(stage), str(package))
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        (output / f"{package.name}.sha256").write_text(f"{digest}  {package.name}\n")
        print(json.dumps({"file": package.name, "sha256": digest, "depends": depends}),
              flush=True)


def smoke() -> None:
    installed = run("dpkg-query", "-W", "-f=${binary:Package}\n").splitlines()
    if any(name.split(":")[0].endswith("-dev") or name == "build-essential"
           for name in installed):
        raise RuntimeError("Runtime image unexpectedly contains build dependencies")
    binaries = [PREFIX / "sbin/guacd", *(PREFIX / "lib").rglob("*.so*")]
    env = {**os.environ, "LD_LIBRARY_PATH": str(PREFIX / "lib")}
    for path in binaries:
        if path.is_file() and not path.is_symlink():
            result = subprocess.run(["ldd", str(path)], env=env, check=True,
                                    text=True, stdout=subprocess.PIPE)
            if "not found" in result.stdout:
                raise RuntimeError(f"Missing runtime library: {path}")
    version = subprocess.run([str(PREFIX / "sbin/guacd"), "-v"], env=env, check=True,
                             text=True, stdout=subprocess.PIPE).stdout
    if SPEC["upstream_version"] not in version:
        raise RuntimeError(f"Unexpected guacd version: {version}")
    with tempfile.TemporaryDirectory() as directory:
        daemon = subprocess.Popen(
            [str(PREFIX / "sbin/guacd"), "-f", "-b", "127.0.0.1", "-l", "41822",
             "-L", "error", "-p", str(Path(directory) / "guacd.pid")], env=env)
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    connection = socket.create_connection(("127.0.0.1", 41822), timeout=1)
                    break
                except OSError:
                    if daemon.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("guacd failed to listen")
                    time.sleep(0.1)
            connection.close()
            for protocol, required in (
                (b"rdp", (b"cert-fingerprints",)),
                (b"ssh", (b"host-key", b"enable-sftp", b"font-name")),
            ):
                with socket.create_connection(("127.0.0.1", 41822), timeout=10) as connection:
                    connection.sendall(b"6.select,3." + protocol + b";")
                    response = b""
                    while b";" not in response:
                        chunk = connection.recv(65536)
                        if not chunk or len(response) + len(chunk) > 65536:
                            raise RuntimeError(f"Invalid {protocol!r} handshake")
                        response += chunk
                    for argument in (b"VERSION_1_5_0", b"disable-copy", b"disable-paste", *required):
                        if argument not in response:
                            raise RuntimeError(f"{protocol!r} handshake missing {argument!r}")
        finally:
            daemon.terminate()
            try:
                daemon.wait(timeout=5)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait(timeout=5)
    print("Runtime dependency and RDP/SSH handshake checks passed", flush=True)


def container_build(engine: str) -> None:
    images = ("public.ecr.aws/docker/library/debian:trixie-slim",
              "mirror.gcr.io/library/debian:trixie-slim",
              "docker.io/library/debian:trixie-slim")
    for image in images:
        try:
            result = subprocess.run([engine, "pull", image], timeout=120, check=False)
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0:
            break
    else:
        raise RuntimeError("Unable to pull Debian Trixie from any registry")
    for phase in ("build", "smoke"):
        name = f"guacamole-{phase}-{os.getpid()}"
        packages = BUILD_PACKAGES if phase == "build" else ("python3",)
        script = (
            "export DEBIAN_FRONTEND=noninteractive\n"
            "apt-get update -qq\n"
            f"apt-get install -y --no-install-recommends ca-certificates {' '.join(packages)}\n"
        )
        if phase == "smoke":
            script += (
                'arch="$(dpkg --print-architecture)"\n'
                f'apt-get install -y --no-install-recommends "/src/dist/{filename("$arch")}"\n'
            )
        script += f"python3 build.py {phase}\n"
        try:
            subprocess.run(
                [engine, "run", "--rm", "--name", name, "--volume", f"{ROOT}:/src",
                 "--workdir", "/src", "--env", "SOURCE_DATE_EPOCH",
                 "--env", "GUACAMOLE_BUILD_COMMIT", image, "bash", "-euc", script],
                check=True, timeout=2400)
        finally:
            subprocess.run([engine, "rm", "-f", name], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "smoke", "container-build"))
    parser.add_argument("--engine", choices=("docker", "podman"), default="docker")
    args = parser.parse_args()
    if args.command == "container-build":
        container_build(args.engine)
    elif args.command == "build":
        build()
    else:
        smoke()
