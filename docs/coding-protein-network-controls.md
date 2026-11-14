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

The first dependency probe (job 1209651) downloaded the five pinned packages but stopped
before any control or model call: the source distribution of rcsb-api needed an isolated
setuptools build environment. The package cache now also downloads setuptools 80.9.0 and
wheel 0.45.1 as build inputs. The original task installation command and source distributions
remain unchanged; these extra wheels are available to pip's isolated build subprocess.
The failed probe and verified instance cleanup are retained in its receipt.

## Public reference compatibility

Job 1209669 passed the offline package-installation probe. Its unmodified online reference
then retrieved public task data but failed during sequence optimization: the RCSB entity
responses for the selected donor and acceptor contain no `modified_monomer` features, leaving
one unknown residue in each sequence. The independent component endpoint still returns the
ordered parent residues for their encoded components. This is a reference/API compatibility
failure, separately recorded from network access and model performance.

`ProteinPublicReferenceControl` makes a labelled copy of the pinned reference script and adds
one fallback: expand parenthesized component IDs using public `chemcomp` metadata when the
original lookup leaves an unknown residue. It records original and patched source hashes.
It uses no scoring constants or cached retrieval answers. The official task files, reference
source, verifier and model-facing inputs remain unchanged.

`run_coding_reference_compatibility.py` requires the four completed original controls, keeps
their outcomes in `reference_network_observations`, and checks the accepted empty submissions.
It executes the compatibility reference online, then restores that accepted submission into
a fresh offline instance through `FileSubmissionRegrader`. Both positive controls must pass
the unchanged official assertions with verified cleanup. The offline result establishes
grading of a valid saved submission, not independent offline solution of the task. Control
records label these two methods explicitly; model groups receive neither reference copy nor
reference submission. Runtime acceptance is established by the resulting receipt, not this plan.
