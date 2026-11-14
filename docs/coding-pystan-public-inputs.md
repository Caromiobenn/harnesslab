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


The public APT stage pins Python 3.10.22-1+noble1 and archives the compiler and
library package closure from the unchanged task image. A real, zero-model probe of
`add-apt-repository -y ppa:deadsnakes/ppa` succeeded in that image. Ubuntu 24.04 emits
one Deb822 `.sources` file containing an inline public signing key; the original probe's
two-file-count predicate was incorrect. Its original record is preserved, and the bytes
used here match its recorded SHA-256:
`4b92f4660bca3776e03329264f89398156f13de893992ce31251df16427bd151`.

The preparation copies those public bytes before APT downloads packages, so no bootstrap
package installation can hide dependencies from APT's resolver. APT verifies the public
repository index using the embedded key. The archive contains installers and repository
metadata, not an installed Python environment, compiled httpstan, model output or solution.

Within task instances, only the exact known `add-apt-repository -y` registration is served
from the frozen metadata; other arguments delegate to the original program. Both network
arms use these same bytes. The command still updates APT and propagates its exit status;
the offline arm's APT configuration points to the local package repository. The wrapper
resides in `/usr/local/bin` so the original `sudo` command finds it through its normal path.
Repository hashes, resolved package versions, an offline installation probe, and cleanup
results are saved in the preparation receipt. The four full native controls remain required
before this task's model cells can be released.
