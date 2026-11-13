# Score and integration denominators

Report official accuracy over every cell with an official score. A zero remains a
zero when the harness or reviewer also reports an error. Excluding scored review
failures would make a less reliable method appear more accurate.

The report separates:

- `valid_scored_cells`: every available official score, including deadlines and
  scored pipeline errors;
- `scored_pipeline_error_cells`: the subset with an integration error;
- `infrastructure_error_cells`: ended cells without an official score;
- `pipeline_error_cells`: all cells whose integration did not complete cleanly.

Usage includes every ended attempt in the selected batches. Missing measurements
stay null. Diagnostic pre-fix batches remain separate from the fixed-protocol
experiment; their costs are retained in the continuation manifest and original
reports. Do not add both a reused outcome and its source batch to the same report.

Two official scores for the same task/group/network/repeat are rejected, even if
one pipeline failed. Paired case and network comparisons keep scored errors and
expose their pipeline status, so failure mechanisms remain available for analysis.
