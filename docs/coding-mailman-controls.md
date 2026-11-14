# Mailman service controls

The pinned Mailman image already contains postfix, mailman3, mailutils and
network-inspection tools. The reference configures the installed services;
the task needs no additional actor package installation. Reuse the accepted
public Python and system verifier caches and test both network arms using
the unchanged empty and reference controls.

Capture the task directory, service configuration, mailing-list database,
local mailboxes, task-created account metadata, and the reference's Mailman
configuration helper. Service processes remain running for the official
verifier. The mail exercise uses local test users and the local.edu test
domain inside the disposable task environment.

The first empty controls exposed a verifier-interpreter mismatch: the official
script created `.tb` with Python 3.12, but the bootstrap's `UV_PYTHON` then sent
`uv pip install` to its managed Python 3.13 installation. Installation failed
and no official test summary was produced. Keep these rejected controls.

The task profile now sets the verifier-only `UV_PYTHON` to
`/app/.tb/bin/python`, the environment created by the unchanged official script.
The existing dependency archive was already prepared and tested with Python
3.12, so its bytes remain unchanged. Actor environment variables are unaffected.
