# Public Git cache compatibility with pip

The MobileSAM reference invokes `pip install git+https://github.com/ChaoningZhang/MobileSAM.git@34bbbfdface3c18e5221aa7de6032d7220c6c6a1`.
Pip clones with `--filter=blob:none`. The previous cache was a depth-one bare repository.
The official controls produced 1,886 and 1,883 repeated filtering warnings before the
instances became unresponsive. Neither control called a model; both failed records remain retained.

Controller job `1209428` reproduced the compatibility problem with a two-commit local repository,
all network protocols disabled except `file`. Ordinary cloning completed in 0.25 seconds.
Both filtered-clone variants timed out at 15 seconds, including a cache with filtering enabled;
their subprocess groups were terminated. Enabling filtering alone is insufficient for a shallow cache.

The MobileSAM recipe now caches the complete ancestry of its existing fixed revision and enables
the cache repository's `uploadpack.allowFilter`. It also verifies pip's filtered clone path offline,
including the checkout and required public files, before exporting an archive. Other task recipes
retain their existing cache behavior. The reference script, model budgets, weights and tests are unchanged.

The regression test creates two real commits, builds the cache using the preparation command,
disables network protocols and checks both the filtered checkout bytes and parent commit.
Successful unit checks are followed by the original empty/reference controls in both network modes.

Git documents the repository setting in [git-config](https://git-scm.com/docs/git-config#Documentation/git-config.txt-uploadpackallowFilter).
