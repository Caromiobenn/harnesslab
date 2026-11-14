"""Attach verified artifact regrades to original traces without rewriting actor records."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from report_coding_study import regrade_scores

from harnesslab.coding.config import project_root, save_json
from harnesslab.coding.observability import persist_feedback, tracing_client


def publish(root: Path, ledgers: list[Path], destination: Path) -> dict:
    rows = regrade_scores(ledgers)
    client, project = tracing_client(root)
    results = []
    for source, row in rows.items():
        original = json.loads(source.read_text())
        if original["reward"] is not None:
            raise ValueError("Artifact feedback cannot replace an existing official score")
        trace = Path(original["trial"]) / "agent/langsmith.json"
        identity = json.loads(trace.read_text())
        run = client.read_run(identity["run_id"])
        values = {
            "official_reward": row["reward"],
            "artifact_regrade": 1,
            "regrade_model_calls": 0,
        }
        started = (
            (original.get("agent_result") or {}).get("metadata", {}).get("started_model_calls")
        )
        received = (original.get("metrics") or {}).get("model_responses")
        if started is not None and received is not None:
            values["usage_complete"] = int(started == received)
        measurements = {
            key: {"score": value, "value": {"raw": value, "unit": "count", "scale": 1}}
            for key, value in values.items()
        }
        receipt = {
            "cell": row["cell"],
            "run_id": identity["run_id"],
            "url": client.get_run_url(run=run, project_name=project),
            "source": row["source"],
            "regrade_trial": row["regrade"]["trial"],
            "model_calls": 0,
            "measurements": measurements,
            "verified": persist_feedback(client, run, identity["run_id"], measurements),
        }
        # Regrading only adds a score. Original pipeline failures, token measurements,
        # trajectories and their existing publication receipts remain unchanged.
        if hashlib.sha256(source.read_bytes()).hexdigest() != row["source"]["outcome_sha256"]:
            raise ValueError("Source outcome changed during feedback publication")
        results.append(receipt)
        save_json(destination, {"ok": False, "model_calls": 0, "outcomes": results})
    result = {"ok": all(row["verified"] for row in results), "model_calls": 0, "outcomes": results}
    save_json(destination, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regrades", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = publish(project_root(), args.regrades, args.output)
    print(json.dumps({"ok": result["ok"], "traces": len(result["outcomes"]), "model_calls": 0}))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
