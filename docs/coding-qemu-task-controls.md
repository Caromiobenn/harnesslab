# QEMU task controls

The pinned images for `qemu-startup` and `qemu-alpine-ssh` already contain QEMU,
the Alpine extended installation ISO, an empty qcow2 disk, and terminal tools.
Reuse the accepted official Python-verifier and system-verifier archives.
The same native runtime preserves the daemonized virtual machine while the
official tests connect to its telnet or SSH service. Internet access stays
disabled throughout the offline actor and verifier phases.

Capture `/app`, which contains the image/disk paths and reference launch/setup
scripts, together with the runtime's process metadata and complete command
trajectory. The filesystem delta records changed host files; it is not a VM
memory snapshot. The official verifier records the live service result before
the cloud instance is deleted.

Run the unchanged empty and reference controls in both network arms. No model
calls occur during these controls, and model tasks remain gated on all four
accepted results per task. The SSH task's reference configures the guest using
the packages supplied by its Alpine image; the offline control establishes
whether that original image is sufficient.
