# Controls for tasks that install public system packages

Eight further tasks use accepted public APT repositories. The actor still installs
the tools it needs, then solves the original task. Both arms use identical installer
bytes; the offline arm resolves packages through the local repository.

The registry preserves `/app` outputs plus Nginx configuration, document roots and
logs; Git-server repository, account and SSH configuration; and SQLite's locally
installed executable path. Background services stay alive through official grading.
Each task gets fresh offline/public empty/reference controls, with source hashes,
network checks, submission deltas and instance cleanup recorded. There are no model
calls in these controls.

The public-cache preparations were accepted in jobs `1208255` and `1208262`.
The first two APT tasks passed all eight controls in job `1208261`. The remaining
eight tasks below are the next control batch; they are not yet model results.

- `nginx-request-logging`
- `configure-git-webserver`
- `dna-assembly`
- `dna-insert`
- `adaptive-rejection-sampler`
- `overfull-hbox`
- `sqlite-with-gcov`
- `make-doom-for-mips`
