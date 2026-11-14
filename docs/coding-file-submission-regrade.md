# Grade a saved file submission

Seven chess trials ended with an API request error before Harbor invoked the
official verifier. Their captured submissions are complete: five contain changed
files or directories and two are unchanged. Restore those exact files into a
fresh copy of the same task image and prerequisite environment, then invoke the
official tests. This makes no actor or grader model request.

The regrader checks the original manifest, archive hash, baseline, environment
fingerprint, template and actor identity. It restores regular files/directories,
then checks both the full filesystem snapshot and the freshly captured delta
against the original. This implementation supports the observed chess captures;
it rejects deletions, links, special files and files changing during capture.

Use `method: "restore_files"` in the selection passed to
`scripts/regrade_coding_unchanged.py`. Existing unchanged-submission selections
keep their original behavior. Results keep source outcome and manifest hashes,
original errors and usage, and an explicit `model_calls: 0` provenance record.
Reporting and LangSmith attach the recovered official score to the original
attempt; they do not create another N1 actor trial.

The public rubric-evidence chess cell already received an official score after
an actor timeout. Preserve that result; it is not one of these seven regrades.
