# Fixed criterion IDs at the rubric boundary

The frozen pilot exposed a concrete mismatch between HarnessLab's evidence gate and
Deep Agents 0.7.14. HarnessLab required the exact names `deliverables`, `behavior`,
`verification`, and `current_evidence`. The native grader schema instead instructed
the model to use descriptive functional sentences, and its first payload asked it to
decompose the rubric itself. The grader complied with that native schema on `regex-log`.

It found a real defect: `foo.1.2.3.4 2020-01-01` did not match because the IPv4
lookbehind also rejected a preceding period. The actor removed that extra restriction.
The grader then returned `satisfied` after checking the changed file, but the evidence
gate rejected its descriptive criterion names. The run reached its 900-second budget;
the final saved artifact still passed the official test. This is an integration defect
in the pilot's termination contract, not evidence that extra repair improves accuracy.

`FixedCriteriaRubric` retains the native iteration loop, transcript delimiter handling,
tools, tracing, status accounting and `GraderResponse` tool name. It changes the grader
factory's response schema to enumerate the caller-owned IDs, validates complete unique
coverage, and seeds the native criteria block from the first pass. Malformed IDs are
corrected inside the grader's structured-output loop rather than causing an unnecessary
actor repair. The evidence gate still requires passing criteria and fresh unchanged
artifact checks; it does not accept descriptive aliases or omit required checks.

The factory override is specific to the pinned Deep Agents 0.7.14 interface. Offline
graph tests exercise malformed-name correction, missing/duplicate IDs, actionable gaps,
native payload escaping, and acceptance of the same candidate with fresh evidence.

This changes both rubric groups' grading contract. The original pilot trajectories and
scores remain intact. Do not pool their rubric results with fixed-contract results as
one frozen experiment; use a new batch/source version and document which unaffected
group cells are compatible for reuse. This note does not authorize best-of-N selection.

Related reporting issue: a zero shell exit code alone does not prove a behavior check
passed. The regex case includes a checker that printed `FAIL` and returned zero, and
commands that printed a test exit status before running a successful checksum command.
Retain command output and distinguish successful command execution from a passed test.
