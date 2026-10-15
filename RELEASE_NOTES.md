Pinned Apache Guacamole 1.6.0 with Basaltwater's RDP and SSH configuration.

Adds the native SSH client, terminal renderer and DejaVu fonts for browser shell
access. Runtime smoke checks now negotiate both RDP and SSH, including SSH host
key pinning support. Authentication and fixed local destinations remain the
responsibility of the Basaltwater gateway.

Packages support Debian 13 (Trixie), amd64. The runtime is
built natively and checked in fresh Debian containers using only the declared
runtime dependencies. The package contains guacd, its private libraries, the
JavaScript client, upstream licenses, and build metadata.

Compilers, development headers, Java, Tomcat, and databases are not runtime
requirements. Basaltwater manages authentication and services separately;
installing this package alone does not start a service.
