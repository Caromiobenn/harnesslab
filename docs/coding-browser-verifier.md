# Explicit browser driver for offline verification

The first cached-data control for `filter-js-from-html` returned official reward 1
offline despite all 28 browser launches failing. The original test catches browser
errors and continues without reporting an alert. An empty/reference score pair alone
therefore did not establish that this verifier was operating correctly.

The prepared verifier now selects the task image's existing `/usr/bin/chromedriver`
through `SE_CHROMEDRIVER`, in both network arms. Selenium 4.35 supports this environment
variable in its Chromium service, allowing DriverFinder to bypass automatic driver
discovery. No official test assertions or browser arguments are changed. The setting
is introduced only for verification, after the actor has submitted.

Acceptance includes both the official empty/reference controls and a separate deliberately
ineffective sanitizer that leaves every HTML file unchanged. The latter must receive
zero reward and exhibit detected alerts in both network arms. Raw rewards, browser
launch/load failures, candidate hashes and instance cleanup records are preserved.

Sources: [Chromium service](https://github.com/SeleniumHQ/selenium/blob/selenium-4.35.0/py/selenium/webdriver/chromium/service.py)
and [driver discovery](https://github.com/SeleniumHQ/selenium/blob/selenium-4.35.0/py/selenium/webdriver/common/driver_finder.py).


## Measured acceptance

Job `1208208` passed all four official empty/reference controls, with every instance confirmed deleted. The reference verifier attempted all 28 browser batches in both network arms and reported 439 vectors. Driver construction failures fell from 28/28 in the previous offline reference to zero. Page-load failures remain visible below; the official test catches these errors and does not treat them as detected alerts, so the reward alone does not demonstrate complete vector coverage.

| Network | Browser attempts | Driver failures | Page-load failures | No-alert batches |
|---|---:|---:|---:|---:|
| public | 28 | 0 | 2 | 26 |
| offline | 28 | 0 | 8 | 20 |

Job `1208209` rejected the unchanged-file candidate in both arms, with actual alerts detected. Candidate SHA-256: `3434dd945f01c35031fc9aaf7f63fd02bc36b885952e32582436560196700c46`. These are verifier diagnostics with zero model calls, separate from the once-per-cell model experiment. All diagnostic instances were confirmed deleted.

Validation: 165 tests passed at 85.69% coverage; Ruff formatting, Ruff checks and the repository smoke run passed.
