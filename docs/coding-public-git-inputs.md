# Pinned public Git inputs

The two source-dependent tasks receive shallow public repositories with fixed
commits. `mteb-leaderboard` uses the August 2025 commit selected by its reference
script. `train-fasttext` uses upstream commit
`1142dc4c4ecbc19cc16eee5cdd28472e689267e6` from March 2024, verified against the
[upstream repository](https://github.com/facebookresearch/fastText/commit/1142dc4c4ecbc19cc16eee5cdd28472e689267e6).

Preparation fetches the full commit and its objects into a bare repository. It
then disables internet access and verifies an ordinary clone and checkout, with
Git permitting only file transport during this probe. The transfer archive and
preparation receipt are hashed. The temporary preparation instance is deleted.

Both experimental network arms receive the same repository bytes and URL
mapping. Other public URLs retain their usual behavior. The mapping is provided
only in task-process environment variables; host Git configuration is unchanged.
These archives contain public source and historical leaderboard data, without
the task's generated answer, trained model, or private tests.

The fastText image requires the public Git and compiler installers. Its official
verifier independently builds the same fixed source; the hidden test data remains
available only during verification. Official empty/reference controls must pass
in both network modes before these tasks enter the model study.
