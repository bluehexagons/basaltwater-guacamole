Pinned Apache Guacamole 1.6.0 with Basaltwater's RDP-only configuration.

Packages support Debian 13 (Trixie), amd64 and arm64. Both architectures are
built natively and checked in fresh Debian containers using only the declared
runtime dependencies. The package contains guacd, its private libraries, the
JavaScript client, upstream licenses, and build metadata.

Compilers, development headers, Java, Tomcat, and databases are not runtime
requirements. Basaltwater manages authentication and services separately;
installing this package alone does not start a service.
