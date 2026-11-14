# Runtime versions in experiment reports

Keep the complete study totals and also report `runtime_cohorts`, grouped by
network, harness, response transport, request adapter and effective model profile.
This separates non-streaming attempts, streaming attempts with the original
image serialization, and attempts using native image blocks. Mini's native shell
interface has its own label. Missing historical profile fields remain null.

Each cohort retains its task list, scored denominator, pass count and the usage
of every ended attempt, including errors and partial responses. Case candidates
and network pairs expose both adapter labels. Saved-submission regrades retain
the original actor's adapter and cost; the regrader is not another actor cohort.

These cohorts run different task subsets. Comparing their aggregate accuracy
does not measure the causal benefit of the image fix. Use the separation to
audit results and identify which runtime produced a case, while analyzing the
five harnesses on matched tasks and network conditions.
