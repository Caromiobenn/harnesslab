# PyStan public inputs

The pinned `rstan-to-pystan` reference installs Python 3.10 from the deadsnakes PPA,
clones httpstan release 4.13.0, builds it from source, and runs the converted analysis.
The task image, official compilation and sampling steps, resources and verifier remain fixed.

The upstream 4.13.0 annotated tag is `f9a5833a5bff4f44489f070fbfb0f20f0dc64d50` and
points to commit `2bb63becd5f9a2931ad0bf48ce9e87b81fbf9eac`. The Git cache fetches the
actual tag object and verifies that an offline `clone --depth 1 --branch 4.13.0` selects
that commit. It archives public source only; task outputs and compiled models are excluded.
The existing full-history cache path remains available for pip's filtered clones.

This stage prepares the Git installer and source repository. Completing the task environment
also requires the public PPA packages, Makefile release downloads, and Python 3.10 package
closure. The bootstrap package cache alone does not establish full environment acceptance.
Formal model cells remain gated on the completed environment controls.

Sources: [upstream release tag](https://api.github.com/repos/stan-dev/httpstan/git/tags/f9a5833a5bff4f44489f070fbfb0f20f0dc64d50)
and [release Makefile](https://github.com/stan-dev/httpstan/blob/4.13.0/Makefile).
