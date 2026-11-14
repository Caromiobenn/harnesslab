# Debian source packages for pMARS

`build-pmars` requires a Debian source package, a build without X11 and an
installed binary. A cache of binary APT packages alone cannot satisfy the
official `apt-get source pmars` step offline.

The preparation job downloads the public Debian 13 (trixie) source package,
generates a normal `Sources` index with `dpkg-scansources`, and includes both
binary and source indexes in the local APT repository. It verifies package
installation and source download with internet access disabled. The receipt
records source archive hashes and the source-index hash.

The cache contains the original Debian sources and public build dependencies.
The actor must extract, configure, compile and install pMARS itself. Capture
`/app` and `/usr/local/bin/pmars`, and require the unchanged official empty and
reference controls in both network conditions before adding model trials.
