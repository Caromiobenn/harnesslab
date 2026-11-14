# Protein task: preserve the network intervention

The fixed `protein-assembly` instruction explicitly requires PDB sequences and FPbase spectra,
in addition to recognizing the input binder and constructing the requested sequence. Those
queries are task work, separate from installing public Python libraries.

This profile caches only biopython 1.85, rcsb-api 1.4.0, dnachisel 3.2.16, pandas 2.2.3,
requests 2.32.4 and their public installation dependencies. It does not prepare RCSB, PubChem
or FPbase query responses, a derived sequence table, a gBlock, or a reference program for actors.
Both network conditions receive the same official image, task files and package cache.

Initial empty/reference controls record how the unchanged reference behaves in each network
condition. An offline reference that cannot retrieve task information is an observation of the
network intervention, rather than evidence that the scoring function itself is broken.
Model trials remain gated until a positive scoring control is verified offline as well.

The planned offline positive control restores the saved output of an accepted online reference
into a fresh task instance, then executes the original verifier with network disabled. Its source
manifest and archive hashes, restoration checks and scoring result must be retained separately
from an independently executed reference. The real model trials receive no reference artifact.
This distinguishes offline grading acceptance from the reference's ability to solve offline,
while retaining all 10 model conditions and the original scoring assertions.

The control implementation and actual outcomes are recorded in subsequent stages; this profile
and plan alone do not establish acceptance or model performance.
