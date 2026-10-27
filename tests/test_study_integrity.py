import copy

import pytest

from harnesslab.reproducibility import canonical_sha256
from harnesslab.study import validate_run_fingerprint, validate_study_progress


def test_deleted_entire_arm_and_entire_task_are_detected_as_missing() -> None:
    schedule = [
        {"arm": arm, "task_ref": task, "repeat": repeat, "seed": repeat}
        for arm in ["default", "rubric"]
        for task in ["one", "two"]
        for repeat in range(2)
    ]
    manifest = {"schedule": schedule}
    complete = [
        {**job, "job_key": canonical_sha256(job), "index": index}
        for index, job in enumerate(schedule)
    ]
    assert not validate_study_progress(manifest, complete)
    assert (
        len(validate_study_progress(manifest, [row for row in complete if row["arm"] != "rubric"]))
        == 4
    )
    assert (
        len(
            validate_study_progress(manifest, [row for row in complete if row["task_ref"] != "two"])
        )
        == 4
    )
    assert len(validate_study_progress(manifest, complete[:-1])) == 1
    with pytest.raises(ValueError, match="duplicate"):
        validate_study_progress(manifest, complete + complete[:1])
    wrong = copy.deepcopy(complete)
    wrong[0]["arm"] = "unplanned"
    with pytest.raises(ValueError, match="disagree"):
        validate_study_progress(manifest, wrong)


@pytest.mark.parametrize("field", ["harness", "public", "private", "lock"])
def test_same_display_names_do_not_allow_incompatible_conditions(field: str) -> None:
    task = "rubric.invoice.holdout.00"
    study = {
        "arm_harness_settings": {"default": {"model": {"name": "same", "temperature": 0.7}}},
        "arm_config_hashes": {"default": "config"},
        "source_hashes": {
            "uv.lock": "lock",
            f"benchmarks/rubric-v1/public/{task}.yaml": "public",
            f"benchmarks/rubric-v1/private/{task}.eval.yaml": "private",
        },
    }
    manifest = {
        "harness": copy.deepcopy(study["arm_harness_settings"]["default"]),
        "config_sha256": "config",
        "lockfile_sha256": "lock",
        "cases": [
            {
                "task_ref": task + "@1",
                "public_file_sha256": "public",
                "private_file_sha256": "private",
            }
        ],
    }
    validate_run_fingerprint(study, "default", manifest, task + "@1")
    if field == "harness":
        manifest["harness"]["model"]["temperature"] = 0
    elif field == "lock":
        manifest["lockfile_sha256"] = "changed"
    else:
        manifest["cases"][0][f"{field}_file_sha256"] = "changed"
    with pytest.raises(ValueError, match=r"incompatible|fingerprint"):
        validate_run_fingerprint(study, "default", manifest, task + "@1")
