# External public data used by the official verifier

The native-control batch found that the official `filter-js-from-html` reference passed
with public networking but failed offline. Its `test_filter_blocks_xss` assertion calls
`urllib.request.urlretrieve` to download the HTML sanitizer testbed from GitHub. The
offline failure was a connection timeout before those browser checks ran. The initial
failed control is preserved under `tb21-native-batch2-20261114`.

`configs/coding-verifier-inputs.json` pins that public archive to repository commit
`b873b79806e166164533109d1055daac00d4d1d3`. Preparation downloads the official URL,
checks the commit embedded in GitHub's ZIP comment, verifies archive paths and records
SHA-256 hashes. The archive is made available only after the actor submits.

The verifier's Python startup hook serves this one exact URL from the checked local
bytes. Other urllib requests keep their existing behavior. This works with the original
`urlretrieve` call; the official test source, payloads and assertions remain unchanged.
Both network arms use the same pinned verifier input. Receipts record each cache hit.
The actor receives no verifier data or startup hook, and required background services
retain the trial's network policy during verification.

The fixture is the public [HTML sanitizer testbed](https://github.com/davidwagner/html-sanitizer-testbed/tree/b873b79806e166164533109d1055daac00d4d1d3).
This adaptation removes a verifier download dependency; fresh empty/reference controls
must still demonstrate the expected zero/one scores with official tests executed.


Job `1208185` produced the expected zero/one scores in all four fresh offline/public empty/reference controls, and all instances were confirmed deleted. Detailed log inspection then found that the offline reference's 28 browser launches all failed even though the official tests returned reward 1. The transport cache works, but this task is not ready for model trials until browser execution and known-bad rejection are verified. Public references ran 28 batches, with 26 no-alert results and two page-load failures. The original offline download failure and these raw scores are retained. A known-bad sanitizer diagnostic was queued separately as job `1208191`. This cache stage passed 165 tests at 85.69% coverage, Ruff and smoke validation.
