"""Judge the tool-return cohort, reusing judgments only for identical requests."""

import argparse
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

STUDY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(STUDY / "audit"))
import run as p1  # noqa: E402


def read_previous(dataset, predictions, model):
    meta = json.loads((predictions.parent / "summary.json").read_text(encoding="utf-8"))
    if (
        meta["configured_model"] != model
        or meta["dataset_manifest_sha256"] != p1.digest((dataset / "manifest.json").read_bytes())
        or meta["execution"] != "online_judge"
    ):
        raise ValueError("Phase 1 source does not match this model or frozen dataset")
    packets, gold = p1.load_dataset(dataset, "full")
    rows = p1.read_jsonl(predictions)
    outcomes = {row["packet_id"]: row for row in rows}
    indexed = {row["packet_id"]: row for row in packets}
    if len(outcomes) != len(rows) or set(outcomes).difference(indexed):
        raise ValueError("Phase 1 predictions contain invalid packet IDs")
    valid = {
        packet_id: {**row, "verdict": p1.parse_verdict(row["content"])}
        for packet_id, row in outcomes.items()
        if "verdict" in row
    }
    readback = p1.summarize(gold, list(outcomes.values()))
    for metric in ("packets_expected", "valid_output_count", "groups"):
        if readback[metric] != meta[metric]:
            raise ValueError(f"Phase 1 readback differs: {metric}")
    return indexed, gold, valid


def paired_scores(old_gold, old, new_gold, new, identical):
    base = {r["packet_id"]: r for r in old_gold}
    views = {}
    for view in p1.VIEWS:
        expected = [
            r for r in new_gold if r["cohort"] == "historical_matched" and r["view"] == view
        ]
        scores = dict(
            expected=len(expected),
            paired_valid=0,
            both_correct_old=0,
            both_correct_new=0,
            improved=0,
            regressed=0,
            identical_requests=0,
        )
        for row in expected:
            pid = row["packet_id"]
            labels = (row["acquisition"], row["use"])
            if (base[pid]["acquisition"], base[pid]["use"]) != labels:
                raise ValueError(f"Reference verdict changed for matching packet {pid}")
            scores["identical_requests"] += pid in identical
            if pid not in old or "verdict" not in new.get(pid, {}):
                continue
            before = tuple(old[pid]["verdict"][k] for k in ("acquisition", "use")) == labels
            after = tuple(new[pid]["verdict"][k] for k in ("acquisition", "use")) == labels
            scores["paired_valid"] += 1
            scores["both_correct_old"] += before
            scores["both_correct_new"] += after
            scores["improved"] += after and not before
            scores["regressed"] += before and not after
        views[view] = scores
    return views


def run(args):
    packets, gold = p1.load_dataset(args.dataset, "full")
    previous_packets, previous_gold, previous = read_previous(
        args.phase1_dataset, args.phase1_predictions, args.model
    )
    identical = {
        packet["packet_id"]
        for packet in packets
        if packet["packet_id"] in previous
        and previous_packets[packet["packet_id"]]["messages"] == packet["messages"]
    }
    todo = [packet for packet in packets if packet["packet_id"] not in identical]
    print(
        f"{len(packets)} verified packets. Reusable: {len(identical)}. New requests: {len(todo)}."
    )
    if args.dry_run:
        return
    if not args.out or not args.env_file:
        raise ValueError("--env-file and a fresh --out directory are required")
    client = p1.DeepSeek.from_env(args.env_file, base_url=args.base_url, model=args.model)
    predictions = [
        {**previous[pid], "judgment_source": "phase1_identical_request"}
        for pid in sorted(identical)
    ]
    args.out.mkdir(parents=True, exist_ok=False)
    random.Random(args.seed).shuffle(todo)
    with (args.out / "predictions.jsonl").open("w", encoding="utf-8") as sink:
        for row in predictions:
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(p1.evaluate, client, packet) for packet in todo]
            for future in as_completed(futures):
                row = {**future.result(), "judgment_source": "phase2_request"}
                predictions.append(row)
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
    report = p1.summarize(gold, predictions)
    indexed = {row["packet_id"]: row for row in predictions}
    report.update(
        {
            "configured_model": args.model,
            "dataset_manifest_sha256": p1.digest((args.dataset / "manifest.json").read_bytes()),
            "phase1_predictions_sha256": p1.digest(args.phase1_predictions.read_bytes()),
            "reused_judgments": len(identical),
            "new_judge_requests": len(todo),
            "new_actor_calls": 0,
            "phase1_matched_comparison": paired_scores(
                previous_gold, previous, gold, indexed, identical
            ),
        }
    )
    (args.out / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Valid outputs: {report['valid_output_count']}/{report['packets_expected']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path(__file__).parent / "dataset")
    parser.add_argument(
        "--phase1-dataset", type=Path, default=STUDY / "artifacts" / "audit-dataset"
    )
    parser.add_argument("--phase1-predictions", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--base-url", default=p1.BASE_URL)
    parser.add_argument("--model", default=p1.MODEL)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args()
    if args.phase1_predictions is None:
        parser.error("--phase1-predictions is required")
    run(args)
