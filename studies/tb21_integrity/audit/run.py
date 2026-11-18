"""Submit blind evidence packets and summarize same-case judgment changes."""

import argparse
import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from build import OUTPUT, VERDICTS, VIEWS, digest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import itertools

from study_client import BASE_URL, MODEL, DeepSeek


def read_jsonl(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def load_dataset(directory, scope):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for filename, expected in manifest["sha256"].items():
        if digest((directory / filename).read_bytes()) != expected:
            raise ValueError(f"Dataset checksum differs: {filename}")
    packets = read_jsonl(directory / "packets.jsonl")
    gold = read_jsonl(directory / "gold.jsonl")
    if [p["packet_id"] for p in packets] != [g["packet_id"] for g in gold]:
        raise ValueError("Packet and reference-label IDs differ")
    if scope == "pilot":
        case_ids = set(manifest["pilot_cases"])
        packets = [p for p in packets if p["case_id"] in case_ids]
        gold = [g for g in gold if g["case_id"] in case_ids]
    return packets, gold


def parse_verdict(content):
    verdict = json.loads(content)
    if not isinstance(verdict, dict) or set(verdict) != {"acquisition", "use", "basis"}:
        raise ValueError("Expected acquisition, use and basis")
    if verdict["acquisition"] not in VERDICTS or verdict["use"] not in VERDICTS:
        raise ValueError("Unknown verdict label")
    if not isinstance(verdict["basis"], str) or not verdict["basis"].strip():
        raise ValueError("Expected textual evidence")
    return verdict


def evaluate(client, packet):
    row = {"packet_id": packet["packet_id"]}
    try:
        response = client.chat(
            packet["messages"],
            max_tokens=192,
            thinking=False,
            temperature=0,
            response_format={"type": "json_object"},
        )
    except RuntimeError as exc:
        return {**row, "error": str(exc), "error_stage": "provider"}
    choice = response["choices"][0]
    content = choice["message"].get("content") or ""
    row.update(
        {
            "content": content,
            "finish_reason": choice.get("finish_reason"),
            "usage": response.get("usage"),
            "model": response.get("model"),
        }
    )
    try:
        row["verdict"] = parse_verdict(content)
    except (ValueError, TypeError) as exc:
        row.update(error=str(exc), error_stage="parse")
    return row


def summarize(gold, predictions):
    by_id = {row["packet_id"]: row for row in predictions}
    expected_ids = {row["packet_id"] for row in gold}
    if len(by_id) != len(predictions) or set(by_id).difference(expected_ids):
        raise ValueError("Unexpected or duplicate prediction IDs")
    groups = {}
    for cohort in sorted({row["cohort"] for row in gold}):
        gold_group = [row for row in gold if row["cohort"] == cohort]
        views = {}
        for view in VIEWS:
            expected = [row for row in gold_group if row["view"] == view]
            available = [row for row in expected if "verdict" in by_id.get(row["packet_id"], {})]
            confusion = {}
            for target in ("acquisition", "use"):
                pairs = Counter(
                    (row[target], by_id[row["packet_id"]]["verdict"][target]) for row in available
                )
                confusion[target] = {
                    answer: {prediction: pairs[(answer, prediction)] for prediction in VERDICTS}
                    for answer in VERDICTS
                }
            views[view] = {
                "expected": len(expected),
                "valid": len(available),
                "both_correct": sum(
                    all(
                        row[target] == by_id[row["packet_id"]]["verdict"][target]
                        for target in ("acquisition", "use")
                    )
                    for row in available
                ),
                "confusion_gold_then_predicted": confusion,
            }
        case_ids = sorted({row["case_id"] for row in gold_group})
        case_lookup = {(row["case_id"], row["view"]): row for row in gold_group}
        transitions = {}
        for left, right in itertools.pairwise(VIEWS):
            transition = {}
            for target in ("acquisition", "use"):
                by_change = Counter()
                for cid in case_ids:
                    previous = by_id.get(f"{cid}:{left}", {}).get("verdict")
                    following = by_id.get(f"{cid}:{right}", {}).get("verdict")
                    if previous is None or following is None:
                        continue
                    before = previous[target] == case_lookup[(cid, left)][target]
                    after = following[target] == case_lookup[(cid, right)][target]
                    by_change[
                        "correct_to_correct"
                        if before and after
                        else "correct_to_wrong"
                        if before
                        else "wrong_to_correct"
                        if after
                        else "wrong_to_wrong"
                    ] += 1
                transition[target] = {
                    k: by_change[k]
                    for k in (
                        "correct_to_correct",
                        "correct_to_wrong",
                        "wrong_to_correct",
                        "wrong_to_wrong",
                    )
                }
            transitions[f"{left}_to_{right}"] = transition
        groups[cohort] = {"cases": len(case_ids), "by_view": views, "paired_changes": transitions}

    return {
        "packets_expected": len(gold),
        "outputs_received": len(predictions),
        "valid_output_count": sum("verdict" in row for row in predictions),
        "errors": dict(Counter(row["error_stage"] for row in predictions if "error_stage" in row)),
        "provider_models": dict(Counter(row["model"] for row in predictions if row.get("model"))),
        "groups": groups,
    }


def run(args):
    packets, gold = load_dataset(args.dataset, args.scope)
    manifest_sha256 = digest((args.dataset / "manifest.json").read_bytes())
    if args.dry_run:
        print(f"Verified {len(packets)} blind packets ready for review")
        return
    if args.out is None:
        raise ValueError("Select a fresh --out directory")
    if args.predictions:
        if args.reuse:
            raise ValueError("Choose --predictions or --reuse")
        predictions = read_jsonl(args.predictions)
        execution = "replay_predictions"
    else:
        if args.env_file is None:
            raise ValueError("--env-file is required for model-assisted review")
        client = DeepSeek.from_env(args.env_file, base_url=args.base_url, model=args.model)
        predictions = []
        if args.reuse:
            previous = json.loads((args.reuse.parent / "summary.json").read_text(encoding="utf-8"))
            if (
                previous["dataset_manifest_sha256"] != manifest_sha256
                or previous["configured_model"] != args.model
            ):
                raise ValueError(
                    "Previous run must use the same dataset manifest and configured model"
                )
            requested_ids = {p["packet_id"] for p in packets}
            predictions = [
                p
                for p in read_jsonl(args.reuse)
                if p["packet_id"] in requested_ids and "verdict" in p
            ]
            used = {p["packet_id"] for p in predictions}
            if len(used) != len(predictions):
                raise ValueError("Duplicate packet IDs in the reused predictions")
            packets = [p for p in packets if p["packet_id"] not in used]
        execution = "online_judge"
    reused = len(predictions) if args.reuse else 0
    args.out.mkdir(parents=True, exist_ok=False)
    if execution == "online_judge":
        random.Random(args.seed).shuffle(packets)
        with (args.out / "predictions.jsonl").open("w", encoding="utf-8") as sink:
            for result in predictions:
                sink.write(json.dumps(result, ensure_ascii=False) + "\n")
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [pool.submit(evaluate, client, packet) for packet in packets]
                for job in as_completed(futures):
                    result = job.result()
                    predictions.append(result)
                    sink.write(json.dumps(result, ensure_ascii=False) + "\n")
                    sink.flush()
    summary = summarize(gold, predictions)
    summary.update(
        {
            "execution": execution,
            "scope": args.scope,
            "configured_model": args.model if execution == "online_judge" else None,
            "dataset_manifest_sha256": manifest_sha256,
            "order_seed": args.seed,
            "reused_judgments": reused,
            "new_judge_requests": len(packets) if execution == "online_judge" else 0,
            "new_actor_calls": 0,
        }
    )
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"Valid outputs: {summary['valid_output_count']}/{summary['packets_expected']} ({args.out / 'summary.json'})"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=OUTPUT)
    parser.add_argument("--scope", choices=("pilot", "full"), default="pilot")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--predictions", type=Path, help="Score an existing prediction file without model calls"
    )
    parser.add_argument(
        "--reuse", type=Path, help="Reuse valid judgments from a completed run on this dataset"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--seed", type=int, default=20261118)
    run(parser.parse_args())
