# Caffe / CIFAR-10 public prerequisites

The fixed Terminal-Bench 2.1 reference installs the Ubuntu build dependencies, clones BVLC Caffe,
checks out `9b89154`, compiles it in CPU-only mode, downloads the original CIFAR-10 binary data,
and trains the model. This profile supplies only the public installers, Git source and raw data.
Compilation, configuration, data conversion and training remain part of the agent/reference run.

The upstream commit resolves to `9b891540183ddc834a02b2bd81b31afae71b2153`.
The upstream download script requests the HTTP CIFAR-10 binary archive. Preparation downloads
the HTTPS version, verifies the publisher's MD5 `c32a1d4ab5d03f1284b67883e8d87530`, and records
a SHA-256 used for every subsequent transfer and cached download. Both original HTTP and HTTPS
URLs map to those identical bytes. No trained weights or converted database is cached.

The two network conditions use the same caches and official CPU, memory and deadline settings.
Empty and reference controls must execute the unchanged official assertions in both modes
before this task is added to the model matrix.

Sources: [BVLC revision](https://github.com/BVLC/caffe/commit/9b891540183ddc834a02b2bd81b31afae71b2153),
[upstream download script](https://github.com/BVLC/caffe/blob/9b891540183ddc834a02b2bd81b31afae71b2153/data/cifar10/get_cifar10.sh),
[CIFAR-10 publisher and checksum](https://www.cs.toronto.edu/~kriz/cifar.html).
