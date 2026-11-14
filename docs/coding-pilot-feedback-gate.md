# Verify final LangSmith receipts when releasing expansion

The real pilot preflight found five older outcome records whose feedback status
still said `uploaded`. Their later `agent/langsmith-metrics.json` receipts were
verified and matched the exact local measurements. The initial expansion gate
therefore stopped before calling any models despite complete monitoring evidence.

The gate now reads the final feedback receipt, requires `verified=true`, and compares
every recorded measurement with the original outcome's canonical measurements.
It retains the receipt path and SHA-256 alongside each preserved pilot outcome.
An old outcome status alone neither blocks nor authorizes expansion.

Tests cover a successful verified receipt with a stale outcome status, missing
receipts, unverified feedback, and mismatched metric values. The complete six-task
matrix and all existing protocol, usage, timing and cleanup checks still apply.
