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
