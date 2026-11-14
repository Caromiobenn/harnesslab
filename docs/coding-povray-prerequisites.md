# POV-Ray 2.2 public prerequisites

The fixed `build-pov-ray` task requires locating and compiling POV-Ray 2.2, including adapting
its legacy C sources to the task's modern system. This profile caches the three raw public
release archives at the original URLs and the exact build tools requested by its reference.

The public-download preparer records SHA-256 values and verifies ordinary `wget` calls offline.
APT dependencies are archived as installers, with their versions and hashes. Compilation,
source patches, executable installation and rendering remain actor work. The profile captures
`/app`, the installed `/usr/local/bin/povray` executable and public-download cache-hit records.

Both network arms receive identical cache bytes and use the original reference and verifier.
Each must pass empty=0 and reference=1 controls before any model attempt is released.
The task retains its official one CPU, 2 GiB RAM and 12,000-second actor/verifier deadlines.

Source: the fixed benchmark revision `12b7565679ce5006230b820666353673a133db93`,
`tasks/build-pov-ray/{instruction.md,task.toml,solution/solve.sh,tests/test.sh}`.
