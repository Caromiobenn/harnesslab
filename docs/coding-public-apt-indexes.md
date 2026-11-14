# Public APT indexes for direct install commands

The chess reference begins with `apt install -y stockfish` and does not refresh
package indexes. The first offline control could install its Python wheels but
APT could not find Stockfish, so the reference emitted an engine-not-found message.
The corresponding public reference passed. Both results are retained.

Public APT archives now include the index files generated for their local package
repository during the existing offline preparation probe. The archive does not
include installed package state or unrelated repository indexes. Their paths,
sizes and SHA-256 values are recorded in `apt_indexes`.

Both network arms receive the same public packages and local indexes. Direct
`apt install` can locate the cached packages immediately, while a later ordinary
`apt update` continues to follow the selected public or offline source list.
The reference script and verifier assertions remain unchanged.
