from __future__ import annotations

import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import build


class SourceIntegrityTests(unittest.TestCase):
    def test_download_checks_pinned_digest_and_uses_source_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            response = io.BytesIO(b"untrusted")
            with patch.object(build.urllib.request, "urlopen", return_value=response) as request:
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    build.download_source("server", Path(directory) / "archive")
            self.assertIn("/1.6.0/source/guacamole-server-", request.call_args.args[0])

    def test_download_bounds_trickling_peer(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(build.urllib.request, "urlopen", return_value=io.BytesIO(b"x")):
                with patch.object(build.time, "monotonic", side_effect=[0, 601]):
                    with self.assertRaisesRegex(RuntimeError, "bounds"):
                        build.download_source("server", Path(directory) / "archive")

    def test_archive_rejects_paths_and_links(self):
        for name, kind in (("../escape", tarfile.REGTYPE),
                           ("/absolute", tarfile.REGTYPE),
                           ("link", tarfile.SYMTYPE),
                           ("hardlink", tarfile.LNKTYPE),
                           ("device", tarfile.CHRTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / "archive.tar.gz"
                with tarfile.open(archive, "w:gz") as output:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    output.addfile(entry)
                with self.assertRaisesRegex(RuntimeError, "Unsafe"):
                    build.extract_source(archive, root / "source")

    def test_archive_preserves_generated_file_timestamps_and_executable_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                entry = tarfile.TarInfo("server/configure")
                entry.size, entry.mode, entry.mtime = 1, 0o755, 1000
                output.addfile(entry, io.BytesIO(b"x"))
            build.extract_source(archive, root / "source")
            info = (root / "source/server/configure").stat()
            self.assertEqual(info.st_mtime, 1000)
            self.assertEqual(info.st_mode & 0o777, 0o755)


class RuntimeDependencyTests(unittest.TestCase):
    def test_dependency_scanning_includes_dynamically_loaded_rdp_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            (release / "sbin").mkdir(parents=True)
            (release / "lib").mkdir()
            (release / "sbin/guacd").touch()
            library = release / "lib/libguac-client-rdp.so.0.0.0"
            library.touch()
            plugin = release / "lib/guac-common-svc.so"
            plugin.touch()
            with patch.object(build, "run", side_effect=[
                "", " (SONAME) [libguac-client-rdp.so.0]",
                " (SONAME) [guac-common-svc.so]",
                "shlibs:Depends=libc6 (>= 2.41), libfreerdp3-3 (>= 3.15.0)"
            ]) as command:
                depends = build.dependencies(root, release)
            self.assertIn("libfreerdp3-3", depends)
            self.assertIn(f"-e{library}", command.call_args.args)
            self.assertIn(f"-e{plugin}", command.call_args.args)
            self.assertIn(f"-x{build.PACKAGE}", command.call_args.args)

    def test_runtime_smoke_rejects_development_packages_before_running_binaries(self):
        with patch.object(build, "run", return_value="libc6:amd64\nfreerdp3-dev:amd64"):
            with self.assertRaisesRegex(RuntimeError, "build dependencies"):
                build.smoke()

    def test_unsupported_architecture_has_no_build_fallback(self):
        for arch in ("arm64", "riscv64"):
            with self.subTest(arch=arch), patch.object(build, "run", return_value=arch):
                with self.assertRaisesRegex(RuntimeError, "Unsupported"):
                    build.architecture()


if __name__ == "__main__":
    unittest.main()
