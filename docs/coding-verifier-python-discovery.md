# Portable discovery of the pinned verifier Python

The shared verifier recipes contain an explicit `uvx -p 3.13`. This takes precedence
over `UV_PYTHON`, so the previously installed, pinned bootstrap interpreter was not
discoverable on images without their own Python 3.13. Preparing the package cache on
the PyPI-server image did not expose this: that image already contained Python 3.13.

The verifier now appends the bootstrap interpreter's bin directory to its PATH after
the original image's directories. Existing system-Python commands keep precedence,
including the Python 3.11 system-pip task. Images without Python 3.13 can discover the
same hash-verified interpreter already installed by verifier bootstrap. No additional
download is needed. The official test commands and package caches are unchanged.

This PATH extension is installed only after the actor phase, together with the other
verifier prerequisites. Actor environments and the running six-task matrix are unchanged.
The failed controls from job `1208092` remain recorded separately from the retry.


## Live acceptance

Job `1208104` completed all eight controls: two tasks, offline/public access, and
empty/official-reference submissions. Both tasks scored empty submissions 0 and
references 1 in both network arms. Polyglot executed its official test instead of
stopping at Python discovery. The Python 3.11 system-pip task still passed all six
additional tests for the reference. All instances were confirmed deleted; no model
calls were made. The source passed 153 tests, 85.59% coverage, Ruff and smoke checks.

The detailed controls, source hashes and prerequisite manifest are under
`artifacts/setup/tb21-native-python-controls-20261114/`. Existing successful package
archives were reused with checksum verification; their dependencies were not fetched
again. This acceptance changes no running pilot source or saved model response.
