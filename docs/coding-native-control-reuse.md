# Reuse accepted controls when expanding the study

The full study retains one model attempt per task, group and network condition.
Already executed empty/reference controls can authorize the new model cells without
creating another pair of cloud instances. Pass an explicit `--controls-manifest` to
the coding runner; model-sample reuse remains a separate `--reuse-manifest`.

Each control reference identifies a frozen acceptance record and its prerequisite
manifest by SHA-256. Reuse checks the benchmark revision, task image, time limits,
exact prerequisite entry, network condition, expected score, executed official
assertions, and verified cleanup. Runtime differences must match the manifest's
reviewed differences and include a compatibility explanation. An accepted task can
be reused from a partially failed batch when its own four controls passed.

The new batch keeps the original trial paths, scores and assertion counts, plus the
acceptance and prerequisite hashes. A control reference cannot replace any model
group. The model still executes once, and valid zero scores remain in the results.

Validation covers both network arms, changed task inputs and time limits, missing
or altered assertion results, incorrect scores, unverified cleanup, duplicate cells,
and unreviewed source changes. A runner-level test confirms that two accepted
controls trigger no new control execution while the selected model executes once.
