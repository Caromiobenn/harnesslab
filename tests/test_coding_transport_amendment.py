import json

import pytest

from harnesslab.coding.config import CodingConfig, save_json
from harnesslab.coding.reuse import digest
from harnesslab.coding.transport_amendment import (
    inherited_transport_attempts,
    reserve_transport_attempts,
)


@pytest.fixture
def scenario(tmp_path):
    origin = tmp_path / "old"
    folder = tmp_path / "new"
    folder.mkdir()
    full = CodingConfig(
        benchmark="terminal-bench-2.1",
        revision="fixture",
        tasks=["pilot", "attempted", "pending", "new"],
        response_transport="streaming",
        purpose="fixture",
    ).model_dump()
    units = [
        {"task": task, "network": net, "groups": full["groups"], "batch": task + "-" + net}
        for task in ("attempted", "pending")
        for net in ("offline", "public")
    ]
    study = {
        "configuration": {**full, "response_transport": "non_streaming"},
        "model_profile": {"model": "fixture"},
        "pilot_tasks": ["pilot"],
        "pilot_batches": [],
        "source_hashes": {},
        "script_hashes": {},
        "ready_tasks": ["attempted", "pending"],
        "units": units,
    }
    path = origin / "study.json"
    save_json(path, study)
    for unit in units[:2]:
        for group in full["groups"]:
            save_json(
                origin / "artifacts/coding" / unit["batch"] / (group + ".outcome.json"),
                {
                    "network_mode": unit["network"],
                    "task": unit["task"],
                    "group": group,
                    "repeat": 0,
                    "reward": None if group == "deepagents_default" else 1,
                    "cleanup_verified": True,
                    "metrics": {"model_responses": 3},
                },
            )
    retirement = {
        "all_jobs_terminal": True,
        "studies": [{"origin": str(path), "sha256": digest(path)}],
        "not_started_cells": [
            [u["network"], u["task"], g, 0] for u in units[2:] for g in full["groups"]
        ],
    }
    retirement_path = tmp_path / "retirement.json"
    save_json(retirement_path, retirement)
    canary_path = tmp_path / "canary.json"
    save_json(
        canary_path,
        {
            "ok": True,
            "configuration": full,
            "rows": [{"group": group, "ok": True} for group in full["groups"]],
        },
    )
    selection = {
        "pilot_tasks": ["pilot"],
        "pilot_batches": [],
        "transport_amendment": {
            "studies": [{"root": str(origin), "study": "study.json", "sha256": digest(path)}],
            "retirement": str(retirement_path),
            "retirement_sha256": digest(retirement_path),
            "canary": str(canary_path),
            "canary_sha256": digest(canary_path),
        },
    }
    return full, selection, {"model": "fixture"}, folder, {"pending", "new"}


def test_transport_replacement_retains_success_and_api_failure_without_resampling(scenario):
    retained, record = reserve_transport_attempts(*scenario)
    assert retained == {"attempted"}
    assert len(record["retained_attempts"]) == 4
    assert sum(r["reward"] is None for r in record["retained_attempts"]) == 2
    assert len(record["replaced_unstarted_cells"]) == 4
    assert json.loads((scenario[3] / "transport-amendment.json").read_text()) == record


@pytest.mark.parametrize(
    "problem",
    [
        "protocol",
        "resample",
        "unfinished",
        "duplicate",
        "unclean",
        "active_queue",
        "canary",
        "omitted",
        "retirement",
    ],
)
def test_transport_replacement_rejects_unsafe_cell_accounting(scenario, problem):
    from pathlib import Path

    full, selection, _, folder, selected = scenario
    amendment = selection["transport_amendment"]
    origin = Path(amendment["studies"][0]["root"])
    outcome = origin / "artifacts/coding/attempted-offline/mini.outcome.json"
    if problem == "protocol":
        full["max_model_calls"] += 1
    elif problem == "resample":
        selected.add("attempted")
    elif problem == "omitted":
        selected.remove("pending")
    elif problem == "unfinished":
        outcome.unlink()
    elif problem == "duplicate":
        (outcome.parent / "duplicate.outcome.json").write_bytes(outcome.read_bytes())
    elif problem == "unclean":
        save_json(outcome, {**json.loads(outcome.read_text()), "cleanup_verified": False})
    else:
        key = "canary" if problem == "canary" else "retirement"
        path = Path(amendment[key])
        record = json.loads(path.read_text())
        if problem == "active_queue":
            record["all_jobs_terminal"] = False
        elif problem == "canary":
            record["rows"][0]["ok"] = False
        else:
            record["not_started_cells"] = []
        save_json(path, record)
        amendment[key + "_sha256"] = digest(path)
    with pytest.raises(ValueError):
        reserve_transport_attempts(*scenario)
    assert not (folder / "transport-amendment.json").exists()


@pytest.mark.parametrize(
    "problem", [None, "resample", "source", "missing_cell", "protocol", "skipped_first", "receipt"]
)
def test_later_streaming_batches_keep_original_api_failures_reserved(scenario, problem):
    from pathlib import Path

    full, original, model, folder, selected = scenario
    retained, record = reserve_transport_attempts(*scenario)
    path = folder / "study.json"
    study = {
        "configuration": full,
        "model_profile": model,
        "prior_studies": [],
        "reserved_prior_tasks": sorted(retained),
        "transport_amendment": record,
    }
    selection = {"pilot_tasks": original["pilot_tasks"], "prior_studies": []}
    if problem == "resample":
        selected.add("attempted")
    elif problem == "source":
        Path(record["retained_attempts"][0]["path"]).write_text("{}")
    elif problem == "missing_cell":
        record["retained_attempts"].pop()
    elif problem == "protocol":
        study["model_profile"] = {"model": "changed"}
    elif problem == "skipped_first":
        study["prior_studies"] = [{"earlier": "missing"}]
    elif problem == "receipt":
        Path(record["canary"]["path"]).write_text("{}")
    save_json(path, study)
    selection["prior_studies"].append(
        {"root": str(folder), "study": "study.json", "sha256": digest(path)}
    )
    destination = folder / "followup"
    if problem:
        with pytest.raises(ValueError):
            inherited_transport_attempts(full, selection, model, destination, selected)
    else:
        tasks, copied = inherited_transport_attempts(full, selection, model, destination, selected)
        assert tasks == {"attempted"} and copied == record
        assert sum(row["reward"] is None for row in copied["retained_attempts"]) == 2


def test_non_amended_continuation_has_no_extra_retained_cells(tmp_path):
    assert inherited_transport_attempts({}, {}, {}, tmp_path, set()) == (set(), None)
    path = tmp_path / "study.json"
    save_json(path, {})
    selection = {
        "prior_studies": [{"root": str(tmp_path), "study": "study.json", "sha256": digest(path)}]
    }
    assert inherited_transport_attempts({}, selection, {}, tmp_path, set()) == (set(), None)
