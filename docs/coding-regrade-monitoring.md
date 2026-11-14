# Artifact regrades in LangSmith

`scripts/publish_coding_regrades.py` validates the complete artifact regrade ledger with the same source hashes, official test counts and cleanup checks used by the study report. It attaches the recovered `official_reward` to the original Deep Agents trace and marks `artifact_regrade=1`, `regrade_model_calls=0` and, when recorded counters permit, `usage_complete`.

The original pipeline error, observed tokens, actor trajectory, outcome file and existing publication receipt remain byte-for-byte unchanged. The new feedback receipt points to both the source outcome and the independent verifier trial. Publishing it again uses the existing deterministic metric IDs; it never invokes the agent or adds another model attempt.

For the six adaptive-rejection-sampler API timeouts, the artifact-only verifier ran all nine official assertions and scored each saved submission zero. These zeros belong to the original six attempts. Interrupted API usage remains incomplete; it is not replaced with zero consumption.
