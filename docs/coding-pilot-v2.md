# Fixed-criterion pilot continuation

The initial HIGH/N=1 pilot exposed a mismatch between Deep Agents' descriptive
criterion names and HarnessLab's fixed identifiers. Commit `ce19f94` fixes that
contract. Results from the earlier two rubric groups remain a diagnostic v1 batch;
they are not pooled with fixed-contract rubric results. This includes valid zeros.
Every fixed-contract cell still has one independent attempt. The extra v1 usage
remains in the development-cost ledger.

Mini, default Deep Agents and generic retry do not invoke the rubric grader. Their
completed scores may be reused after reviewing the exact source differences,
model profile, task definitions, prerequisites, network condition and budgets.
Cleanup failures have no official verdict; retain their costs and rerun only after
the cleanup fix. A scored harness failure is still a retained sample.

`harnesslab.coding.cli run --reuse-manifest /absolute/path/reuse.json` accepts an
explicit compatibility manifest. It checks source/record hashes before launching
any new instance. Reused outcomes retain their original job, trial, metrics and
LangSmith identities and add source references. No fake execution configuration is
created for reused work. Completed controls can also be referenced after the same
compatibility review. `--resume` only resumes an identical frozen plan.

The first fixed-contract acceptance is the offline `regex-log/rubric_evidence`
cell, with fresh empty/reference controls. Its result is retained regardless of
score. Once its integration is checked, the remaining cells complete the same
60-cell pilot. Full-dataset model work follows that pilot acceptance.
