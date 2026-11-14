import json
from pathlib import Path

import pytest
from test_coding_transport_amendment import scenario as scenario

from harnesslab.coding.config import save_json
from harnesslab.coding.image_amendment import inherited_image_attempts, reserve_image_attempts
from harnesslab.coding.reuse import digest
from harnesslab.coding.transport_amendment import reserve_transport_attempts


@pytest.fixture
def image_scenario(scenario):
    full, selection, model, folder, _ = scenario
    retained, transport = reserve_transport_attempts(*scenario)
    units = [
        {"task": task, "network": net, "groups": full["groups"], "batch": task + "-" + net}
        for task in ("pending", "new")
        for net in ("offline", "public")
    ]
    path = folder / "study.json"
    save_json(
        path,
        {
            "configuration": full,
            "model_profile": model,
            "prior_studies": [],
            "pilot_tasks": selection["pilot_tasks"],
            "pilot_batches": selection["pilot_batches"],
            "reserved_prior_tasks": sorted(retained),
            "transport_amendment": transport,
            "ready_tasks": ["pending", "new"],
            "source_hashes": {},
            "script_hashes": {},
            "units": units,
        },
    )
    for unit in units[:2]:
        for group in full["groups"]:
            save_json(
                folder / "artifacts/coding" / unit["batch"] / (group + ".outcome.json"),
                {
                    "task": unit["task"],
                    "network_mode": unit["network"],
                    "group": group,
                    "repeat": 0,
                    "reward": None,
                    "cleanup_verified": True,
                    "metrics": {"model_responses": 48},
                },
            )
    retirement = folder / "image-retirement.json"
    save_json(
        retirement,
        {
            "all_jobs_terminal": True,
            "studies": [{"origin": str(path), "sha256": digest(path)}],
            "not_started_cells": [
                [u["network"], u["task"], g, 0] for u in units[2:] for g in full["groups"]
            ],
        },
    )
    canary = folder / "image-canary.json"
    save_json(
        canary,
        {
            "ok": True,
            "expected": "ABC123",
            "observed": "ABC123",
            "configuration": full,
            "effective_model_profile": {"max_input_tokens": 1000000},
            "usage": {"input_tokens": 600},
            "wire": [{"image_blocks": 1, "base64_in_tool_text": False, "stream": True}],
        },
    )
    selection = {
        "pilot_tasks": selection["pilot_tasks"],
        "pilot_batches": selection["pilot_batches"],
        "image_amendment": {
            "studies": [{"root": str(folder), "study": "study.json", "sha256": digest(path)}],
            "retirement": str(retirement),
            "retirement_sha256": digest(retirement),
            "canary": str(canary),
            "canary_sha256": digest(canary),
        },
    }
    return full, selection, model, folder / "image", {"new"}


def test_image_amendment_keeps_api_errors_and_earlier_transport_attempts(image_scenario):
    tasks, transport, record = reserve_image_attempts(*image_scenario)
    assert tasks == {"attempted", "pending"}
    assert len(record["retained_attempts"]) == 8
    assert sum(row["reward"] is None for row in record["retained_attempts"]) == 6
    assert len(record["replaced_unstarted_cells"]) == 4
    assert record["configuration_changed"] is False
    assert record["effective_model_profile"]["max_input_tokens"] == 1000000
    assert transport["to"] == "streaming"


@pytest.mark.parametrize("problem", ["text_image", "wrong_answer", "active", "resample", "prior"])
def test_image_release_requires_acceptance_retirement_and_no_resampling(image_scenario, problem):
    _, selection, _, _, selected = image_scenario
    amendment = selection["image_amendment"]
    if problem == "resample":
        selected.add("pending")
    elif problem == "prior":
        selection["prior_studies"] = amendment["studies"]
    else:
        name = "retirement" if problem == "active" else "canary"
        path = Path(amendment[name])
        record = json.loads(path.read_text())
        if problem == "active":
            record["all_jobs_terminal"] = False
        elif problem == "wrong_answer":
            record["observed"] = "wrong"
        else:
            record["wire"][0]["base64_in_tool_text"] = True
        save_json(path, record)
        amendment[name + "_sha256"] = digest(path)
    with pytest.raises(ValueError):
        reserve_image_attempts(*image_scenario)


@pytest.mark.parametrize("problem", [None, "source", "missing", "protocol", "resample", "receipt"])
def test_later_batches_inherit_every_original_image_error(image_scenario, problem):
    full, selection, model, folder, _ = image_scenario
    tasks, transport, record = reserve_image_attempts(*image_scenario)
    path = folder / "study.json"
    previous = {
        "configuration": full,
        "model_profile": model,
        "prior_studies": [],
        "reserved_prior_tasks": sorted(tasks),
        "image_amendment": record,
        "transport_amendment": transport,
    }
    selected = set()
    if problem == "source":
        Path(record["retained_attempts"][0]["path"]).write_text("{}")
    elif problem == "missing":
        record["retained_attempts"].pop()
    elif problem == "protocol":
        previous["model_profile"] = {"model": "changed"}
    elif problem == "resample":
        selected.add("pending")
    elif problem == "receipt":
        Path(record["canary"]["path"]).write_text("{}")
    save_json(path, previous)
    followup = {
        "pilot_tasks": selection["pilot_tasks"],
        "prior_studies": [{"root": str(folder), "study": "study.json", "sha256": digest(path)}],
    }
    if problem:
        with pytest.raises(ValueError):
            inherited_image_attempts(full, followup, model, folder / "followup", selected)
    else:
        actual, copied_transport, copied_image = inherited_image_attempts(
            full, followup, model, folder / "followup", selected
        )
        assert actual == tasks and copied_transport == transport and copied_image == record


def test_other_studies_have_no_image_amendment(tmp_path):
    assert reserve_image_attempts({}, {}, {}, tmp_path, set()) == (set(), None, None)
    assert inherited_image_attempts({}, {}, {}, tmp_path, set()) == (set(), None, None)
    path = tmp_path / "study.json"
    save_json(path, {})
    selection = {
        "prior_studies": [{"root": str(tmp_path), "study": "study.json", "sha256": digest(path)}]
    }
    assert inherited_image_attempts({}, selection, {}, tmp_path, set()) == (set(), None, None)
