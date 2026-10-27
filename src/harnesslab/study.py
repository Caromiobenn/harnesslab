"""Validate planned coverage and compatibility before combining study artifacts."""

from typing import Any

from harnesslab.reproducibility import canonical_sha256


def validate_study_progress(manifest: dict[str, Any], progress: list[dict]) -> list[str]:
    planned = {
        canonical_sha256(job): (index, job) for index, job in enumerate(manifest["schedule"])
    }
    if len(planned) != len(manifest["schedule"]):
        raise ValueError("study schedule contains duplicate cells")
    seen = set()
    for entry in progress:
        key = entry["job_key"]
        if key in seen:
            raise ValueError("duplicate matrix jobs found")
        if key not in planned:
            raise ValueError("result does not belong to the planned study schedule")
        index, job = planned[key]
        if entry["index"] != index or any(
            entry.get(field) != value for field, value in job.items()
        ):
            raise ValueError("job key, assignment, or schedule index disagree")
        seen.add(key)
    return sorted(set(planned) - seen)


def validate_run_fingerprint(study: dict, arm: str, run_manifest: dict, task_ref: str) -> None:
    if run_manifest["harness"] != study["arm_harness_settings"][arm]:
        raise ValueError("incompatible model, sampling, grader, or treatment settings")
    if run_manifest["config_sha256"] != study["arm_config_hashes"][arm]:
        raise ValueError("configuration fingerprint differs from the frozen study")
    if run_manifest["lockfile_sha256"] != study["source_hashes"]["uv.lock"]:
        raise ValueError("lockfile fingerprint differs from the frozen study")
    cases = run_manifest["cases"]
    if len(cases) != 1 or cases[0]["task_ref"] != task_ref:
        raise ValueError("run contains the wrong task assignment")
    task_id = task_ref.split("@")[0]
    for directory, suffix, field in [
        ("public", ".yaml", "public_file_sha256"),
        ("private", ".eval.yaml", "private_file_sha256"),
    ]:
        key = f"benchmarks/rubric-v1/{directory}/{task_id}{suffix}"
        if cases[0][field] != study["source_hashes"][key]:
            raise ValueError("public task or private evaluation fingerprint changed")
