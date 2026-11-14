# Reporting recovered scores and incomplete response usage

Pass completed artifact-only regrade ledgers with `report_coding_study.py
--regrades /absolute/path/to/results.json`. The report checks the original
outcome and submission hashes, regrade provenance, official reward, official
test summary, and verified cleanup. It rejects duplicate recovery records and
attempts to overwrite an existing official score.

`reward` becomes the recovered official score; `original_reward` remains null,
and `score_source` identifies the saved-submission regrade. The original
`pipeline_ok=false`, exception, actor usage and elapsed time remain visible.
The separate regrade trial path provides the verifier runtime and logs. A
regrade adds no actor attempt and contributes no second set of actor tokens.

Reports also expose response transport and the number of started Deep Agents
requests. When more requests started than completed, `usage_completeness` is
`partial`: token totals cover received responses and cannot include the
provider's unreported usage for the interrupted request. If a harness does not
provide this counter, completeness is `not_reported`. Missing counters are not
inferred from a successful score. Group summaries include regraded-cell,
partial-usage and transport counts alongside accuracy and resource metrics.
