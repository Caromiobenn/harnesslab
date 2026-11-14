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


The Makefile download stage caches the exact pybind11 2.9.2, RapidJSON 1.1.0,
Stan 2.35.0, Math 4.9.0 and Linux stanc 2.35.0 URLs from that frozen source commit.
The download helper can install curl from the previously accepted public APT cache
inside its temporary preparation instance. Only the raw downloads and URL transport
helper are archived. The actor still installs curl, runs the original Makefile, compiles
httpstan, and performs task sampling. Both network arms use identical pinned downloaded
bytes, with checksums recorded in the receipt; unknown URLs retain normal curl behavior.

The offline probe invokes curl with the Makefile's normal location/output options and
checks every resulting file hash. A regression test exercises actual curl with HTTP
protocols disabled. This is dependency acceptance, not a completed task run; Python
package closure and all four native task controls must pass before model release.


The Python package stage resolves and downloads the public task libraries for both
the reference's Python 3.10 and the image's native Python. It creates a temporary
Python 3.10 venv using only the accepted APT installers; the secondary interpreter's
offline import probe uses an isolated installation target. These probe environments
are never archived. Each interpreter must install and import the requested packages
with the network disabled and pip's public index disabled during the probe.

The actor archive contains ordinary public distribution files only. It includes the
publicly published httpstan 4.13.0 wheels as well as PyStan, matching normal pip
availability for an actor choosing that route. The original reference remains unchanged
and builds httpstan from its pinned source. Poetry 1.8.5 satisfies the reference's
`~=1.8` requirement; setuptools 70.3.0 satisfies its final `<71` compatibility requirement.
Both network arms receive the same installer files. Per-interpreter resolved package
versions, file hashes, import results and cleanup are retained in the cache receipt.


Package resolution follows the reference's installation phases: pip/build utilities,
Poetry, then PyStan and analysis libraries. Poetry 1.8.5 requires crashtest 0.4.x,
while PyStan's clikit dependency requires crashtest 0.3.x. A single combined resolver
request is unsatisfiable; the reference intentionally uses Poetry before installing
PyStan. Download phases therefore retain both required public distributions, and the
offline probe installs them in the same order. The initial combined-resolution failure
and its verified instance cleanup are preserved as zero-model preparation evidence.


The task capture profile preserves `/app`, containing the converted script, its input
files and the four required output CSV files. Public repository and download cache-hit
logs are also captured. The original verifier runs in the task instance and checks both
outputs and the prohibition on R/RStan. Capturing `/app` alone does not preserve all
system package state for a later replay; the original native verifier result remains the
scoring record for these controls.

The package cache passed offline installation/import checks in both interpreters before
the profile was added. A missing profile stopped control setup before any task control
instance or model call; the accepted package receipt is reused without rebuilding it.
Preparation receipts retain actual versions separately for each interpreter: an isolated
native-Python probe can resolve transitive build-tool versions differently from Python
3.10. The original reference's final `setuptools<71` installation remains unchanged.

The first complete native control run passed the public reference (6/6), while the
offline reference reached the original 1,800-second deadline at 88% of sampling.
Its build succeeded, but the output CSV files were not yet written (1/6 official
checks passed). The failed native run and its costs remain preserved.

The earlier package import probe explicitly disabled pip's public index; the runtime
receipt instead provided local find-links without replacing the public index. Under
network denial, pip could still spend time attempting that unreachable index for each
dependency. The PyStan recipe now uses the existing `offline_local_index` option, so
the offline runtime selects the local wheel directory as its index as well as its
find-links location. The public arm retains normal public-index access. Both arms
receive the same public installer archive, and package pins, original reference,
sampling settings and official deadline remain unchanged. New native controls must
verify this configuration before the task's model cells are released.
