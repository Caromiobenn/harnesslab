# LangSmith metric units and persistence checks

Real pilot traces exposed a constraint not exercised by the zero-model monitoring smoke:
the feedback API accepts scores only between -99,999.9999 and 99,999.9999. An unscaled
input-token count of 162,219 caused HTTP 422. The asynchronous batch did not persist its
feedback even though the SDK returned feedback objects and the local queue drained.

Native LLM token usage remains in tokens. Custom feedback measurements ending in
`tokens` or `chars` use a `_millions` suffix and divide the displayed score by 1,000,000.
Every feedback item additionally carries `value.raw`, `value.unit`, and `value.scale`.
The original integer token/character counts and full-precision durations remain in
`agent/metrics.json` and `value.raw`; four-decimal feedback scores are display values.

`scripts/sync_coding_langsmith.py` reads completed local outcomes, resolves the run's
project/time keys, writes feedback synchronously, and then verifies the exact raw values
by reading them back from LangSmith. Only this readback produces a verified
`agent/langsmith-metrics.json` receipt. The script skips already verified, unchanged
measurements and never calls a model or repeats a benchmark trial.

During pilot job 1207614 the actor code stayed frozen and the reporting script repaired
feedback independently. The next execution version uses the same synchronous publisher
for new trials and historical synchronization, with deterministic feedback IDs and exact
raw-value readback. Only verified persistence is reported as `feedback_status=verified`.

`agent_execution_phase_seconds` additionally exposes Harbor's recorded actor phase,
including shutdown/draining. It remains distinct from `agent_seconds`, which stops at
the execution deadline and excludes capture. When a shutdown error prevented the latter
measurement, its missing value stays missing and the recorded phase duration is retained.
