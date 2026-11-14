# Local package service and archive task prerequisites

`pypi-server` uses cached public APT and Python installers. The package versions
come from the pinned image and official reference installation commands. Both
network arms receive identical installer bytes. Public APT sources remain
enabled in the online arm; offline APT uses the local package repository.
Python uses `PIP_FIND_LINKS`, preserving explicit localhost package indexes.
No `vectorops` implementation or package is supplied by these caches.

The native submission profile captures the local service configuration, hosted
packages, build source, service log, and installed Python tools.
The service stays alive for official
verification; capture records changed files and process metadata.

`crack-7z-hash` uses its official task image, which already contains the pinned
John build and task archive. Public APT installers provide the reference's
Perl LZMA module and 7zip. Submitted task files remain under `/app`.

Prepare and verify each installer archive offline, then run empty and reference
controls in both network modes. All preparation and control steps make zero
model calls. Only accepted controls can release the later model experiment.
