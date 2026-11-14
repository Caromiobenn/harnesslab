"""Continue unstarted cells after fixing image serialization, retaining all attempts."""

from pathlib import Path

from harnesslab.coding.config import save_json
from harnesslab.coding.deepseek_adapter import aliyun_deepseek_profile
from harnesslab.coding.reuse import checked_json
from harnesslab.coding.transport_amendment import (
    collect_retired_attempts,
    inherited_transport_attempts,
)


def reserve_image_attempts(full, selection, model_profile, folder, selected):
    amendment = selection.get("image_amendment")
    if amendment is None:
        return set(), None, None
    if (
        selection.get("prior_studies")
        or full.get("response_transport") != "streaming"
        or len(amendment["studies"]) != 1
    ):
        raise ValueError("Image replacement requires the retired first streaming cohort")
    retirement = checked_json(Path(amendment["retirement"]), amendment["retirement_sha256"])
    if not retirement["all_jobs_terminal"]:
        raise ValueError("Retire the previous queue before preparing replacement cells")
    canary = checked_json(Path(amendment["canary"]), amendment["canary_sha256"])
    if (
        not canary["ok"]
        or canary["expected"] != canary["observed"]
        or len(canary["wire"]) != 1
        or canary["wire"][0]["image_blocks"] != 1
        or canary["wire"][0]["base64_in_tool_text"]
        or not canary["wire"][0]["stream"]
        or not 0 < canary["usage"]["input_tokens"] < 5000
        or canary["effective_model_profile"]["max_input_tokens"] != 1_000_000
        or any(
            canary["configuration"][key] != full[key]
            for key in (
                "thinking",
                "reasoning_effort",
                "temperature",
                "top_p",
                "response_transport",
            )
        )
    ):
        raise ValueError("Native image transport requires successful real API acceptance")
    inherited_selection = {**selection, "prior_studies": amendment["studies"]}
    inherited, transport = inherited_transport_attempts(
        full, inherited_selection, model_profile, folder, selected
    )
    if transport is None:
        raise ValueError("The image amendment must retain the earlier transport amendment")
    tasks, attempts, unstarted, studies = collect_retired_attempts(
        full, selection, model_profile, amendment, full, retirement, selected
    )
    if tasks & inherited:
        raise ValueError("An earlier task was resampled")
    record = {
        "from": "json_tool_content",
        "to": "native_tool_images_v1",
        "configuration_changed": False,
        "effective_model_profile": aliyun_deepseek_profile(
            full["context_window_tokens"], full["max_output_tokens"]
        ),
        "studies": studies,
        "retained_attempts": [*transport["retained_attempts"], *attempts.values()],
        "replaced_unstarted_cells": [list(cell) for cell in sorted(unstarted)],
        "canary": {"path": amendment["canary"], "sha256": amendment["canary_sha256"]},
        "retirement": {"path": amendment["retirement"], "sha256": amendment["retirement_sha256"]},
    }
    save_json(folder / "image-amendment.json", record)
    return tasks | inherited, transport, record


def inherited_image_attempts(full, selection, model_profile, folder, selected):
    priors = selection.get("prior_studies", [])
    if not priors:
        return set(), None, None
    reference = priors[0]
    previous = checked_json(Path(reference["root"]) / reference["study"], reference["sha256"])
    record = previous.get("image_amendment")
    if record is None:
        return set(), None, None
    if (
        previous["configuration"] != full
        or previous["model_profile"] != model_profile
        or previous.get("prior_studies")
        or record["to"] != "native_tool_images_v1"
    ):
        raise ValueError("First predecessor must be the original native-image replacement")
    transport = previous["transport_amendment"]
    for amendment in (record, transport):
        for name in ("canary", "retirement"):
            checked_json(Path(amendment[name]["path"]), amendment[name]["sha256"])
    cells = []
    for saved in record["retained_attempts"]:
        outcome = checked_json(Path(saved["path"]), saved["sha256"])
        cell = (outcome["network_mode"], outcome["task"], outcome["group"], outcome["repeat"])
        if (
            list(cell) != saved["cell"]
            or not outcome["cleanup_verified"]
            or (outcome.get("metrics") or {}).get("model_responses", 0) < 1
        ):
            raise ValueError("Retained image-cohort attempt is incomplete")
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
        raise ValueError("Reserve every retained image-cohort cell without resampling")
    save_json(folder / "image-amendment.json", record)
    save_json(folder / "transport-amendment.json", transport)
    return tasks, transport, record
