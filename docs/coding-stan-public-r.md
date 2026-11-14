# RStan public source preparation

`mcmc-sampling-stan` explicitly passes `repos='https://cloud.r-project.org/'` when it
installs its R packages. A default `options(repos=...)` alone cannot provide an offline cache
for those calls. This preparation adds an exact-URL transport for public CRAN package sources
and package metadata, then runs the original pinned installation calls with internet disabled.

The reference pins Rcpp 1.1.0, RcppEigen 0.3.4.0.2, BH 1.87.0-1, StanHeaders 2.32.10 and
rstan 2.32.7. Preparation verifies each source package's DESCRIPTION, resolves its Depends,
Imports and LinkingTo closure against CRAN metadata compatible with the native R version,
and records all downloaded package versions, hashes and URLs. Existing base/recommended
packages remain those in the official image. The dependency snapshot is shared by both network
conditions and by all five harness groups.

Only the source repository and download metadata are archived. Compiled R libraries, the
temporary build library, Stan model, posterior samples and task answers are excluded.
The actor/reference still installs and compiles packages and performs the original MCMC run
under the official task resources and time limit. Preparation installs and loads the pinned
packages in a temporary library to prove that the source cache is sufficient offline.

The R transport serves only listed URLs, checks cached bytes, and records each cache hit.
Other requests use the original download function. The source cache is exposed through the
existing `actor_r` family; public system installers use the existing `actor_system` family.
Four unchanged official empty/reference controls are required before model execution.

The first preparation (job 1209632) downloaded and verified 48 source packages, then stopped
at R startup because `assignInNamespace` was referenced before utils was attached. The profile
used `utils::assignInNamespace` explicitly in the next attempt. Job 1209642 then showed that
this helper refuses to replace utils' locked binding. Both failed instances were deleted and
verified absent, with zero model calls; the accepted system-package archive is reused.

The profile now explicitly unlocks, assigns and relocks only utils' `download.file` binding.
Native-image canary 1209650 verified R startup, cached-file retrieval and fallback to the original
download implementation. A second check changed the cached bytes and confirmed rejection.
The canary completed in nine seconds, made zero model calls and verified instance deletion.

Source: [remotes 2.5.0 download implementation](https://github.com/r-lib/remotes/blob/v2.5.0/R/download.R),
which calls `utils::download.file` for the R version in the task image.
