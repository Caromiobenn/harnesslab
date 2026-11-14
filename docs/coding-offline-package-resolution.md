# Resolve cached package installers offline

The disposable Python-package acceptance probe uses `PIP_NO_INDEX=1` after
internet access is disabled. This verifies that the downloaded wheel files
contain all installation dependencies without waiting on an unreachable public
index. It changes preparation only; ordinary actor recipes keep their existing
runtime settings.

`pypi-server` additionally selects a local file index in the offline runtime,
alongside `PIP_FIND_LINKS`. Its online runtime keeps the normal public index.
An explicit `pip --index-url http://localhost:8080/simple` overrides the default
index, allowing official tests to install the submitted package from the running
service. The actor runtime does not set `PIP_NO_INDEX` for this task.

Keep the timed-out preparation receipt and its verified instance deletion. Reuse
the successful system installer archives; prepare a fresh Python installer
receipt and rerun the official empty/reference controls before model execution.
