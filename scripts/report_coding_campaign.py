"""Report all frozen predecessor batches, including retired setup failures."""

import argparse
from pathlib import Path

from report_coding_study import make_report, write_report

from harnesslab.coding.config import save_json
from harnesslab.coding.reuse import checked_json, digest


def campaign_inputs(study_path, study_sha256):
    pending = [(Path(study_path).resolve(), study_sha256)]
    studies, batches = {}, {}
    configuration = None
    while pending:
        path, expected = pending.pop(0)
        study = checked_json(path, expected)
        if path in studies:
            continue
        studies[path] = expected
        if configuration is None:
            configuration = study["configuration"]
        # Expansion manifests have the fixed layout artifacts/expansions/<run>/study.json.
        root = path.parents[3]
        for batch in study["pilot_batches"]:
            batches[str((root / "artifacts/coding" / batch).resolve())] = None
        for unit in study["units"]:
            batches[str((root / "artifacts/coding" / unit["batch"]).resolve())] = None
        references = list(study.get("prior_studies", []))
        for name in ("transport_amendment", "image_amendment"):
            amendment = study.get(name) or {}
            references.extend(amendment.get("studies", []))
            for retained in amendment.get("retained_attempts", []):
                saved = Path(retained["path"])
                checked_json(saved, retained["sha256"])
                batches[str(saved.parent.resolve())] = None
        pending.extend((Path(row["origin"]).resolve(), row["sha256"]) for row in references)
    return configuration, list(batches), {str(path): sha for path, sha in studies.items()}


def campaign_report(study_path, study_sha256, regrades=()):
    config, batches, studies = campaign_inputs(study_path, study_sha256)
    report = make_report(Path(study_path).resolve().parents[3], config, batches, regrades)
    expected = {
        (network, task, group, repeat)
        for network in ("offline", "public")
        for task in config["tasks"]
        for group in config["groups"]
        for repeat in range(config["repeats"])
    }
    observed = {(r["network"], r["task"], r["group"], r["repeat"]) for r in report["trials"]}
    if not observed <= expected:
        raise ValueError("An observed cell is outside the campaign matrix")
    scored = sum(row["valid_scored_cells"] for row in report["groups"])
    report["campaign"] = {
        "study": str(Path(study_path).resolve()),
        "study_sha256": study_sha256,
        "studies": studies,
        "batches": batches,
        "expected_cells": len(expected),
        "ended_cells": len(observed),
        "scored_cells": scored,
        "unscored_cells": len(expected) - scored,
        "ended_attempts": len(report["trials"]),
        "successes": sum(row["successes"] for row in report["groups"]),
        "outcome_sha256": {
            r["outcome_path"]: digest(Path(r["outcome_path"])) for r in report["trials"]
        },
        "regrade_sha256": {str(path): digest(Path(path)) for path in regrades},
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--study-sha256", required=True)
    parser.add_argument("--regrades", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = campaign_report(args.study, args.study_sha256, args.regrades)
    write_report(report, args.output)
    save_json(args.output / "campaign.json", report["campaign"])


if __name__ == "__main__":
    main()
