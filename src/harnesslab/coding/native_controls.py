"""Compose verified public caches and evaluate native task controls."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def public_cache(root: Path, origin: dict) -> dict:
    """Reuse an accepted archive without duplicating large immutable cache files."""
    source_root = Path(origin["root"])
    receipt = source_root / origin["receipt"]
    if hashlib.sha256(receipt.read_bytes()).hexdigest() != origin["receipt_sha256"]:
        raise ValueError("Cache preparation receipt changed")
    saved = json.loads(receipt.read_text())
    if not saved["ok"] or not saved["cleanup"]["verified"] or saved["model_calls"] != 0:
        raise ValueError("Public cache preparation did not pass")
    artifact = saved["archive"]
    if artifact != origin["archive"]:
        raise ValueError("Cache ledger disagrees with its preparation receipt")
    source = source_root / artifact["archive"]
    destination = root / artifact["archive"]
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != artifact["sha256"]:
            raise ValueError("Prepared public archive changed")
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, destination)
    with destination.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != artifact["sha256"]:
            raise ValueError("Destination public archive changed")
    return saved


def task_prerequisites(root: Path, row: dict, capture_paths: list[str], ledger: dict) -> dict:
    """Build one explicit profile from pinned test source and accepted public receipts."""
    task = row["task"]
    families = ledger["families"]
    choices = [value for value in families["shared_python"].values() if task in value["tasks"]]
    if task in families["custom_python"]:
        choices.append(families["custom_python"][task])
    if len(choices) != 1:
        raise ValueError("Task needs exactly one public Python cache recipe")
    python = public_cache(root, choices[0])
    system = public_cache(root, families["system"][task])
    test_sha = hashlib.sha256((Path(row["path"]) / "tests/test.sh").read_bytes()).hexdigest()
    recipe_sha = (
        python["test_script_sha256"]
        if "test_script_sha256" in python
        else python["recipe"]["test_script_sha256"][task]
    )
    if recipe_sha != test_sha:
        raise ValueError("Python cache does not match the official test script")
    if system["source_fingerprint"] != row["source_fingerprint"]:
        raise ValueError("System cache does not match the official task image")
    if python.get("source_fingerprint", row["source_fingerprint"]) != row["source_fingerprint"]:
        raise ValueError("Custom Python cache does not match the official task image")
    entry = {
        "runtime_profile": "native",
        "source_fingerprint": row["source_fingerprint"],
        "capture_paths": capture_paths,
        "archives": [],
        "env": {},
        "verifier": {
            "archives": [python["archive"], system["archive"]],
            "downloads": python["downloads"],
            "env": python["env"],
            "install_command": system["install_command"],
            "test_script_sha256": test_sha,
        },
    }
    for family in ("actor_python", "actor_hub"):
        if task not in families.get(family, {}):
            continue
        actor = public_cache(root, families[family][task])
        if actor["source_fingerprint"] != row["source_fingerprint"]:
            raise ValueError("Actor public cache does not match the official task image")
        entry["archives"].append(actor["archive"])
        entry["env"].update(actor["env"])
        entry.setdefault("offline_env", {}).update(actor.get("offline_env", {}))
    if task in families.get("verifier_inputs", {}):
        inputs = public_cache(root, families["verifier_inputs"][task])
        if (
            inputs["source_fingerprint"] != row["source_fingerprint"]
            or inputs["test_script_sha256"] != test_sha
        ):
            raise ValueError("Public verifier inputs do not match the official task")
        entry["verifier"]["archives"].append(inputs["archive"])
        entry["verifier"]["python_downloads"] = inputs["python_downloads"]
    return entry


def official_control_result(outcome: dict, expected: float) -> dict:
    """Require executed official assertions, expected score and verified cleanup."""
    trial = Path(outcome["trial"]) if outcome.get("trial") else None
    ctrf = trial / "verifier/ctrf.json" if trial else None
    tests = json.loads(ctrf.read_text())["results"]["summary"] if ctrf and ctrf.exists() else None
    accepted = bool(
        outcome["pipeline_ok"]
        and outcome["reward"] == expected
        and outcome["cleanup_verified"]
        and tests
        and tests["tests"] > 0
    )
    return {**outcome, "ctrf_summary": tests, "control_accepted": accepted}
