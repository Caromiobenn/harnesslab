# Verifier cache runtime compatibility

The third native control batch found two failures before official assertions ran:

- `pytorch-model-recovery`: GNU tar rejected a directory inode change while unpacking
  the 2,987,720,919-byte shared verifier archive in both network arms.
- `reshard-c4-data`: the image's uv 0.8.15 could not resolve pytest from a cache prepared
  with the pinned uv 0.9.5; both official runs returned zero without producing CTRF.

Verifier archives are now extracted with the controller's pinned Python tarfile module
after the existing transfer hash check. This preserves the archive's file contents,
hard links, symbolic links and executable modes without GNU tar's delayed inode check.
These archives are prepared by the controller, rather than supplied by the actor.

The verifier PATH now selects the same pinned uv/uvx binaries used to build its cache.
Image Python precedence is retained. This applies only after actor submission and does
not change the task's original test script or assertions. The original failed controls
remain available for inspection; fresh controls validate the new runtime separately.

The inode error is consistent with a documented overlay-filesystem failure, but the
cloud kernel cause has not been established. See the [Canonical report](https://lists.ubuntu.com/archives/kernel-team/2017-October/087930.html)
and [GNU tar's directory metadata behavior](https://www.gnu.org/software/tar/manual/html_node/Directory-Modification-Times-and-Permissions.html).
