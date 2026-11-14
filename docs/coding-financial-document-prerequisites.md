# Financial document task dependencies

The task image supplies uv but has no general Python installation. The official
reference uses a PEP 723 script requiring Python 3.13 and eleven pinned packages,
and installs Tesseract through APT. Cache those exact public dependencies and the
managed interpreter under the existing public dependency prefix.

The online preparation script only imports libraries and prints their versions.
A second script at a different path must resolve and run with the network
disabled. This checks that the cache can provision a new script environment.
The archived bytes contain public interpreter/package files and generic probe
environment metadata; they contain no task documents, OCR output, classifications,
amounts, CSV result or reference implementation. The actor's own script still
performs the document processing.

Both network arms receive the same immutable archive. Public mode can access
package indexes; offline mode sets `UV_OFFLINE=1`. Keep the official task image,
resource and time limits, documents, reference implementation and tests intact.
Require four empty/reference controls before scheduling any model cells.
