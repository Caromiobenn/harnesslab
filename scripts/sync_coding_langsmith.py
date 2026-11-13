"""Attach canonical local measurements to completed traces and verify server persistence."""

import argparse
import json
import time
from pathlib import Path
from uuid import UUID, uuid5

from harnesslab.coding.observability import tracing_client


def measurements(outcome):
    metrics = outcome["metrics"]
    values = {
        "official_reward": outcome["reward"],
        "pipeline_ok": int(outcome["pipeline_ok"]),
        "model_calls": metrics["model_responses"],
        "tool_calls": metrics["model_issued_tool_calls"],
        "environment_commands": metrics["environment_commands"],
        "command_failures": metrics["environment_command_failures"],
        "agent_seconds": metrics["agent_seconds"],
        "trial_seconds": metrics["trial_seconds"],
        "submission_capture_seconds": metrics["submission_capture_seconds"],
        "review_candidates": metrics["candidates"],
        "evidence_checks": metrics["evidence_checks"],
        **metrics["tokens_and_lengths"],
    }
    grader = (metrics.get("role_usage") or {}).get("grader") or {}
    values.update({"grader_" + key: value for key, value in grader.items()})
    result = {}
    for key, raw in values.items():
        if raw is None:
            continue
        scaled = key.endswith(("tokens", "chars"))
        unit = (
            "tokens"
            if key.endswith("tokens")
            else "characters"
            if key.endswith("chars")
            else ("seconds" if key.endswith("seconds") else "count")
        )
        scale = 1_000_000 if scaled else 1
        name = key + "_millions" if scaled else key
        # LangSmith feedback scores have four decimals and an absolute limit below 100,000.
        result[name] = {
            "score": round(raw / scale, 4),
            "value": {"raw": raw, "unit": unit, "scale": scale},
        }
    return result


def synchronize(root, batches):
    client, project = tracing_client(root)
    records = []
    for batch in batches:
        for path in sorted((root / "artifacts/coding" / batch).glob("*.outcome.json")):
            outcome = json.loads(path.read_text())
            if not outcome.get("langsmith") or not outcome.get("metrics"):
                continue
            trace = outcome["langsmith"]
            receipt = Path(outcome["trial"]) / "agent/langsmith-metrics.json"
            expected = measurements(outcome)
            if receipt.exists():
                saved = json.loads(receipt.read_text())
                if saved.get("verified") and saved.get("measurements") == expected:
                    records.append(saved)
                    continue
            run = client.read_run(trace["run_id"])
            existing = {item.key: item for item in client.list_feedback(run_ids=[run.id])}
            for key, item in expected.items():
                previous = existing.get(key)
                if previous and previous.value == item["value"]:
                    continue
                if previous:
                    client.update_feedback(previous.id, score=item["score"], value=item["value"])
                else:
                    # Synchronous writes surface API validation errors before recording success.
                    client.create_feedback(
                        run_id=run.id,
                        session_id=run.session_id,
                        start_time=run.start_time,
                        key=key,
                        score=item["score"],
                        value=item["value"],
                        feedback_id=uuid5(UUID(trace["run_id"]), "harnesslab-metric-v2:" + key),
                        comment="Canonical local measurement; value.raw preserves the exact value.",
                    )
            for _attempt in range(6):
                observed = {item.key: item for item in client.list_feedback(run_ids=[run.id])}
                verified = all(
                    key in observed and observed[key].value == item["value"]
                    for key, item in expected.items()
                )
                if verified:
                    break
                time.sleep(2)
            record = {
                "task": outcome["task"],
                "group": outcome["group"],
                "network": outcome["network_mode"],
                "run_id": trace["run_id"],
                "url": trace.get("url") or client.get_run_url(run=run, project_name=project),
                "verified": verified,
                "measurements": expected,
            }
            receipt.write_text(json.dumps(record, indent=2))
            records.append(record)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--batches", nargs="+", required=True)
    args = parser.parse_args()
    records = synchronize(args.root, args.batches)
    print(
        json.dumps(
            {
                "completed_traces": len(records),
                "verified": sum(record["verified"] for record in records),
            }
        )
    )
    raise SystemExit(0 if all(record["verified"] for record in records) else 1)


if __name__ == "__main__":
    main()
