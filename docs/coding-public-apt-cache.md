# Public system installers for offline tasks

Some official reference programs install tools such as GnuCOBOL, Stockfish or Nginx.
The actor receives an ordinary local APT repository containing public installers and
their resolved dependencies. The prepared archive contains no task solution and does
not install these tools before the actor starts. The actor or reference still runs its
normal `apt-get update` and `apt-get install` commands.

Preparation uses each task's original image to resolve missing packages from its
configured public distribution sources. Package metadata, versions, content hashes,
image fingerprint and archive hashes are recorded. A disposable preparation instance
then disables internet access and installs the requested tools through the local
repository. That instance is deleted after the probe.

Both network arms receive identical installer bytes. `APT_CONFIG` selects a source
list containing the original public sources plus the local repository online, and
only the local repository offline. The local index records each package's SHA-256;
the local unsigned index is trusted only after archive transfer verification. Public
repository authentication during the original download remains enabled.

The setting uses documented [APT configuration](https://manpages.debian.org/trixie/apt/apt.conf.5.en.html)
and [file repository sources](https://manpages.debian.org/trixie/apt/sources.list.5.en.html).
The cache ledger's `actor_system` family composes these archives with any Python or
model/data cache for the same task. Accepted package preparation is followed by fresh
empty/reference controls before the corresponding model trials.

```bash
python scripts/prepare_coding_actor_system.py \
  --dataset /path/to/pinned-dataset \
  --run public-apt-acceptance \
  --tasks cobol-modernization merge-diff-arc-agi-task
```

Recipes are recorded in `configs/coding-actor-system.json`. Every task uses the same
network, dependency and capture settings across its five agent groups. Model sampling
remains HIGH with one independent attempt per cell.


## Verified acceptance

Jobs `1208255` and `1208262` prepared all 13 recipes and verified ordinary package installation with internet disabled. Every preparation instance was confirmed deleted. Job `1208261` then passed eight fresh offline/public empty/reference controls across `cobol-modernization` and `merge-diff-arc-agi-task`, with all instances cleaned. The published stage passed 165 tests at 85.69% coverage, Ruff checks and the smoke run. Remaining recipes still require their task-level controls.
