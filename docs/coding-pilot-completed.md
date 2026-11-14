# Six-task HIGH study: completed acceptance

The six tasks completed all **60** cells: 6 tasks × 5 groups × 2 network modes × 1 attempt. Official verification passed **49/60** cells. All scored trials have the nine required usage, output-length and timing measurements and verified instance deletion. All **48** Deep Agents trials have matching verified LangSmith measurement receipts.

Ten earlier CompCert setup failures made zero model calls. Their records remain in the 70-attempt report; the later ten trials were the first actual model attempts for those cells. No scored zero was resampled.

## Score and resource totals

Each row aggregates 12 scored cells, including failures. Time is the sum of per-trial agent elapsed time, not elapsed time of the concurrent study.

| Group | Passes | Model responses | Tool calls | Input tokens | Output tokens | Agent seconds |
|---|---:|---:|---:|---:|---:|---:|
| mini | 9/12 | 386 | 402 | 17563903 | 333065 | 3962.57 |
| deepagents_default | 10/12 | 638 | 748 | 22991371 | 740754 | 6158.3 |
| generic_retry | 10/12 | 818 | 963 | 35624261 | 1042784 | 11149.07 |
| rubric_transcript | 10/12 | 800 | 933 | 31162737 | 918890 | 8277.66 |
| rubric_evidence | 10/12 | 740 | 838 | 21193637 | 864020 | 6997.65 |

| Group | Visible output characters | Reasoning characters | Tool argument characters |
|---|---:|---:|---:|
| mini | 18724 | 873189 | 232917 |
| deepagents_default | 33590 | 2061524 | 322025 |
| generic_retry | 68638 | 3055708 | 382997 |
| rubric_transcript | 38090 | 2566632 | 413466 |
| rubric_evidence | 47735 | 2385152 | 436601 |

All four Deep Agents configurations passed 10/12 cells. This pilot therefore shows differences in resource use but no pass-count gain from review. The per-task cases explain concrete behavior: [Cython cost](case-cython-equal-score-different-cost.md), [Raman submission timeout](case-raman-submission-timeout.md), and [WAL read side effects](case-wal-read-side-effect.md). The [browser verifier case](case-offline-browser-false-acceptance.md) is a constructed verifier control, separate from observed model behavior.

## Frozen evidence and full-study start

The final report is saved at `artifacts/coding-reports/pilot-final-high-n1-20261114/report.json` with SHA-256 `46053ae1cd770a625094b3ae1e1f64828af817740167528e8dfb3e55d8b35d77`. It retains individual rows and the source batch paths.

CPU release job `1208346` checked all 60 scores, protocol settings, measurements, deletion receipts and Deep Agents feedback receipts. It completed successfully and released array `1208347` at source commit `681d24292fa4c2c5a967a6daccb69a9661d614ee`. Its first two units are the offline/public adaptive-rejection-sampler task; both wrote successful pilot-gate receipts, frozen plans and live mini-swe-agent trajectories.

This first full-study batch contains 58 additional tasks and 580 new model cells, with two concurrent actors. The complete scope remains 89 tasks and 890 cells. Subsequent task batches must exclude already reserved cells and wait for the preceding array to finish before occupying the same concurrency budget.

Five further tasks passed all 20 current-runtime controls in CPU job `1208387`: fix-code-vulnerability, log-summary-date-ranges, openssl-selfsigned-cert, polyglot-c-py, and sqlite-db-truncate. Their 50 model cells are ready for a later batch. PyPI/archive and public-Git task controls are tracked separately and do not modify the running 58-task plan.
