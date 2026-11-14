# Submission deltas for tasks with large inputs

Full-dataset tasks include large datasets, model weights, source trees and service
configuration outside `/app`. Recopying every unchanged input after every trial
adds transfer cost without improving evidence of the submitted work.

`submission_delta.snapshot` fingerprints the selected public workspace before
the actor starts. `capture_delta` saves changed/new files, directory/link metadata
and a deletion list. The manifest includes archive SHA-256/size and the hashes of
the actual archived file bytes. Files that changed between fingerprinting and
archiving are identified rather than described as an atomic snapshot.

The trial must also save the baseline inventory and its template, prerequisite
and capture-path provenance. Replaying the archive requires that same baseline.
Symlink targets are recorded without being followed. Socket/special-file paths
are listed as metadata; live services and VM memory require their own state
records. This component does not claim a full machine checkpoint.

Tests reconstruct an edited workspace from its baseline and archive, including
new files, deletions and executable permissions, while leaving a large unchanged
input out of the archive. Runtime integration and task-specific path selection
follow in the full-dataset environment branch; the pilot capture stays frozen.
