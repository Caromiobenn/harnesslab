"""Retain attempted cells when replacing unstarted queues after a transport fix."""

from pathlib import Path

from harnesslab.coding.config import save_json
from harnesslab.coding.reuse import checked_json, digest


def inherited_transport_attempts(full, selection, model_profile, folder, selected):
    """Carry the first streaming cohort's completed old attempts into later batches."""
    priors = selection.get("prior_studies", [])
    if not priors:
        return set(), None
    reference = priors[0]
    path = Path(reference["root"]) / reference["study"]
    previous = checked_json(path, reference["sha256"])
    record = previous.get("transport_amendment")
    if record is None:
        return set(), None
    if (
        previous["configuration"] != full
        or previous["model_profile"] != model_profile
        or previous.get("prior_studies")
        or record["from"] != "non_streaming"
        or record["to"] != "streaming"
        or full.get("response_transport") != "streaming"
    ):
        raise ValueError("The first predecessor must be the original streaming replacement")
    for name in ("canary", "retirement"):
        checked_json(Path(record[name]["path"]), record[name]["sha256"])
    cells = []
    for saved in record["retained_attempts"]:
        outcome = checked_json(Path(saved["path"]), saved["sha256"])
        cell = (outcome["network_mode"], outcome["task"], outcome["group"], outcome["repeat"])
        if (
            list(cell) != saved["cell"]
            or not outcome["cleanup_verified"]
            or (outcome.get("metrics") or {}).get("model_responses", 0) < 1
        ):
            raise ValueError("Retained actor attempt is unclosed or disagrees with its source")
        cells.append(cell)
    tasks = {cell[1] for cell in cells}
    expected = {
        (net, task, group, 0)
        for task in tasks
        for net in ("offline", "public")
        for group in full["groups"]
    }
    if (
        len(cells) != len(expected)
        or set(cells) != expected
        or not tasks <= set(full["tasks"])
        or tasks & (selected | set(selection["pilot_tasks"]))
        or tasks != set(previous["reserved_prior_tasks"])
    ):
        raise ValueError("Streaming continuation must reserve every original attempted cell")
    save_json(folder / "transport-amendment.json", record)
    return tasks, record


def reserve_transport_attempts(full, selection, model_profile, folder, selected):
    amendment = selection.get("transport_amendment")
    if amendment is None:
        return set(), None
    if selection.get("prior_studies") or full.get("response_transport") != "streaming":
        raise ValueError("Transport replacement requires a separate streaming cohort")
    retirement = checked_json(Path(amendment["retirement"]), amendment["retirement_sha256"])
    if not retirement["all_jobs_terminal"]:
        raise ValueError("Previous queues must finish or be cancelled before replacement")
    canary = checked_json(Path(amendment["canary"]), amendment["canary_sha256"])
    if (
        not canary["ok"]
        or len(canary["rows"]) != 2
        or {r["group"] for r in canary["rows"]} != {"mini", "deepagents_default"}
        or not all(r["ok"] for r in canary["rows"])
        or any(
            canary["configuration"][key] != full[key]
            for key in (
                "thinking",
                "reasoning_effort",
                "temperature",
                "top_p",
                "request_timeout",
                "response_transport",
            )
        )
    ):
        raise ValueError("Both agent transports require successful API acceptance")
    old_protocol = {**full, "response_transport": "non_streaming"}
    retained_tasks, attempted, unstarted, studies = collect_retired_attempts(
        full, selection, model_profile, amendment, old_protocol, retirement, selected
    )
    record = {
        "from": "non_streaming",
        "to": "streaming",
        "studies": studies,
        "retained_attempts": list(attempted.values()),
        "replaced_unstarted_cells": [list(cell) for cell in sorted(unstarted)],
        "canary": {"path": amendment["canary"], "sha256": amendment["canary_sha256"]},
        "retirement": {"path": amendment["retirement"], "sha256": amendment["retirement_sha256"]},
    }
    save_json(folder / "transport-amendment.json", record)
    return retained_tasks, record


def collect_retired_attempts(
    full, selection, model_profile, amendment, old_protocol, retirement, selected
):
    """Validate closed attempts and replacement cells against the retired queue."""
    all_cells, attempted, unstarted, studies = set(), {}, set(), []
    for reference in amendment["studies"]:
        origin = Path(reference["root"])
        path = origin / reference["study"]
        study = checked_json(path, reference["sha256"])
        if (
            {"response_transport": "non_streaming", **study["configuration"]} != old_protocol
            or study["model_profile"] != model_profile
            or study["pilot_tasks"] != selection["pilot_tasks"]
            or study["pilot_batches"] != selection["pilot_batches"]
        ):
            raise ValueError("Only response transport may change across the replacement")
        for name, sha in {**study["source_hashes"], **study["script_hashes"]}.items():
            if digest(origin / name) != sha:
                raise ValueError("Previously frozen source changed")
        cells = [(u["network"], u["task"], g, 0) for u in study["units"] for g in u["groups"]]
        expected = {
            (net, task, group, 0)
            for net in ("offline", "public")
            for task in study["ready_tasks"]
            for group in full["groups"]
        }
        if len(cells) != len(expected) or set(cells) != expected or all_cells & expected:
            raise ValueError("Earlier studies contain missing or duplicated cells")
        all_cells.update(expected)
        for unit in study["units"]:
            batch = origin / "artifacts/coding" / unit["batch"]
            unit_cells = {(unit["network"], unit["task"], group, 0) for group in unit["groups"]}
            found = set()
            for outcome in batch.glob("*.outcome.json"):
                import json

                row = json.loads(outcome.read_text())
                if row["group"] in ("empty", "oracle"):
                    continue
                cell = (row["network_mode"], row["task"], row["group"], row["repeat"])
                if cell not in unit_cells or cell in attempted or not row["cleanup_verified"]:
                    raise ValueError("An attempted cell is duplicated, unclosed, or out of scope")
                if (row.get("metrics") or {}).get("model_responses", 0) < 1:
                    raise ValueError("Classify setup-only attempts separately before replacement")
                attempted[cell] = {
                    "cell": list(cell),
                    "path": str(outcome),
                    "sha256": digest(outcome),
                    "reward": row["reward"],
                }
                found.add(cell)
            if batch.exists() and found != unit_cells:
                raise ValueError("An earlier execution unit has unfinished cells")
            unstarted.update(unit_cells - found)
        studies.append({"origin": str(path), "sha256": reference["sha256"]})
    retained_tasks = {cell[1] for cell in attempted}
    retained_cells = {
        (net, task, group, 0)
        for net in ("offline", "public")
        for task in retained_tasks
        for group in full["groups"]
    }
    if set(attempted) != retained_cells or retained_tasks & selected:
        raise ValueError("Retain every attempted task; never resample its cells")
    if not {cell[1] for cell in unstarted} <= selected:
        raise ValueError("Replacement omitted an unstarted task")
    if (
        retirement["studies"] != studies
        or set(map(tuple, retirement["not_started_cells"])) != unstarted
    ):
        raise ValueError("Queue retirement does not match the cells being replaced")
    return retained_tasks, attempted, unstarted, studies
