"""Score saved unchanged submissions in fresh task environments, with zero actor calls."""

import argparse
from pathlib import Path

from harnesslab.coding.config import CodingConfig, configure_runtime, project_root, save_json
from harnesslab.coding.native_controls import official_control_result
from harnesslab.coding.regrade import file_submission, unchanged_submission
from harnesslab.coding.reuse import checked_json
from harnesslab.coding.runner import execute_stage, task_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    args = parser.parse_args()
    root = project_root()
    configure_runtime(root)
    selection = checked_json(args.selection, args.selection_sha256)
    restore_files = selection.get("method") == "restore_files"
    validate = file_submission if restore_files else unchanged_submission
    folder = root / "artifacts/regrades" / selection["run"]
    if folder.exists():
        raise ValueError("Regrade results are immutable; inspect the existing run")
    folder.mkdir(parents=True)
    outcomes = []
    for index, reference in enumerate(selection["sources"]):
        original = checked_json(Path(reference["outcome"]), reference["outcome_sha256"])
        manifest = validate(Path(reference["manifest"]), reference["manifest_sha256"])
        config = CodingConfig.model_validate(original["agent_result"]["metadata"]["configuration"])
        config = config.model_copy(
            update={
                "prerequisites_manifest": selection["prerequisites"],
                "network_mode": original["network_mode"],
            }
        )
        row = task_plan(root, config, original["task"])
        if row["source_fingerprint"] != manifest["source_fingerprint"]:
            raise ValueError("Saved submission uses another task environment")
        result = execute_stage(
            root,
            folder,
            row,
            "empty",
            config,
            selection["run"],
            index,
            False,
            agent_override={
                "import_path": "harnesslab.coding.regrade:"
                + ("FileSubmissionRegrader" if restore_files else "UnchangedSubmissionRegrader"),
                "kwargs": {
                    "network_mode": original["network_mode"],
                    "source_manifest": reference["manifest"],
                    "source_sha256": reference["manifest_sha256"],
                },
            },
        )
        checked = official_control_result(result, result["reward"])
        record = {
            "cell": [
                original["network_mode"],
                original["task"],
                original["group"],
                original["repeat"],
            ],
            "source": reference,
            "original_exception": original["exception"],
            "original_metrics": original["metrics"],
            "reward": result["reward"],
            "accepted": checked["control_accepted"],
            "ctrf_summary": checked["ctrf_summary"],
            "regrade": result,
            "model_calls": 0,
        }
        outcomes.append(record)
        save_json(
            folder / "results.json",
            {
                "run": selection["run"],
                "expected": len(selection["sources"]),
                "outcomes": outcomes,
                "ok": len(outcomes) == len(selection["sources"])
                and all(r["accepted"] for r in outcomes),
                "model_calls": 0,
            },
        )
    if not all(r["accepted"] for r in outcomes):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
