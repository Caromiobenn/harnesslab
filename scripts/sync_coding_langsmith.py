"""Synchronize completed local outcomes with the same verified publisher used by new trials."""

import argparse
import json
from pathlib import Path

from harnesslab.coding.observability import publish_trial


def synchronize(root, batches):
    records = []
    for batch in batches:
        for path in sorted((root / "artifacts/coding" / batch).glob("*.outcome.json")):
            outcome = json.loads(path.read_text())
            if outcome.get("langsmith") and outcome.get("metrics"):
                records.append(publish_trial(root, Path(outcome["trial"]), outcome))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--batches", nargs="+", required=True)
    args = parser.parse_args()
    records = synchronize(args.root, args.batches)
    verified = sum(
        bool(record and record.get("feedback_status") == "verified") for record in records
    )
    print(json.dumps({"completed_traces": len(records), "verified": verified}))
    raise SystemExit(0 if verified == len(records) else 1)


if __name__ == "__main__":
    main()
