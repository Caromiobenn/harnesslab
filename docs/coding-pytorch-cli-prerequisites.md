# PyTorch CLI task prerequisites

`pytorch-model-cli` keeps its official Python 3.13 image, one CPU, 2 GiB RAM,
900-second actor deadline and 900-second verifier deadline. The actor receives
public installers for `build-essential`, `torch==2.7.0+cpu` and `numpy==2.3.1`.
PyTorch 2.7.0 matches the official reference's CPU installation; NumPy is pinned
to the official verifier version. Nothing is compiled or converted before the
actor starts. In particular, the cache contains no `cli_tool`, converted model
weights, predicted digit or reference implementation.

The official tests use torchvision 0.22.1 to fetch MNIST. Its
[pinned source](https://github.com/pytorch/vision/blob/v0.22.1/torchvision/datasets/mnist.py)
lists four downloads and their MD5 checksums. Preparation verifies these upstream
checksums and records SHA-256 for the saved bytes. The files are installed only
at verifier startup, through the existing exact-URL download cache, after the
actor submission has been captured. The
[download implementation](https://github.com/pytorch/vision/blob/v0.22.1/torchvision/datasets/utils.py)
reads the response length, which the local response now supplies.

Acceptance requires offline installation/import of the actor packages and four
official controls: empty submission must fail and the reference must pass in
both network modes. The actor's task files and the official verifier assertions
are unchanged. These preparation and control jobs use no model calls or GPU.
