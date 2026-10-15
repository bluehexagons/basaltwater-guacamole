# Basaltwater Guacamole binaries

This repository builds an RDP and SSH Apache Guacamole runtime for Basaltwater.
It tracks pinned Apache source archives rather than maintaining a source fork.
Basaltwater's authenticated Python gateway and systemd services live in the
[main repository](https://github.com/bluehexagons/basaltwater).

The initial packages support Debian 13 (Trixie) on amd64 and arm64. They include
guacd, its private libraries, and the JavaScript client. Development headers,
static libraries, Java, Tomcat, and databases are omitted. Normal Debian shared
libraries are declared as package dependencies, allowing APT security updates.
The package alone does not configure or start services.

## Build and verification

The release manifest pins both Apache archives by SHA-256. The builder rejects
unsafe archive entries, enables RDP and SSH terminal support, and derives runtime package
dependencies using dpkg-shlibdeps. Builds run natively on each architecture in
Debian containers; no emulation is needed.

Each package is then installed into a fresh Debian container. Verification
checks for missing libraries, confirms that no development packages were
installed, and exercises the native daemon's RDP and SSH protocol negotiation.
SSH terminal rendering includes Pango and DejaVu fonts. VNC, Telnet, Kubernetes,
SFTP services, recording tools and audio codecs are not configured by the builder.
Basaltwater's gateway restricts connections and disables transfer channels.

The development checkout on the shared Basaltwater VM is
`/home/agent/repos/basaltwater-guacamole`; the main integration checkout is
`/home/agent/repos/infra-tools`. These paths describe that VM, not installer paths.

For a local native build with Docker:

    python3 -m unittest discover -s tests
    python3 build.py container-build

For Podman, add --engine podman. Build dependencies stay inside the temporary
container. Distribution output goes into dist/. SOURCE_DATE_EPOCH and the build
commit are recorded or applied when provided. Debian dependency updates can
change binaries, so this is not a promise of bit-for-bit reproducibility.

## Publishing

Update release.json with reviewed Apache source hashes and a new build/package
version, then commit and push. After the branch build passes, tag that commit as
v followed by the build_version and push the tag. Tag CI rebuilds, verifies both
architectures, and publishes versioned packages with SHA-256 files. Existing
releases are never overwritten by the workflow.

Before updating Basaltwater, inspect the release run and pin the SHA-256 of each
downloaded package in its installer. The installer must not trust a mutable
latest URL or an unpinned checksum downloaded alongside the package. Unsupported
platforms should fail explicitly rather than compile source on the target.

## Licensing

The build tooling is licensed under Apache License 2.0. The upstream runtime
retains Apache's LICENSE and NOTICE files in the package's share directory.
Apache Guacamole is a project of the Apache Software Foundation; these builds
are distributed by Basaltwater.
