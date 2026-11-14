import hashlib
import json

import pytest

from harnesslab.coding.cache_recipes import recipe_inventory, uv_recipe


def test_recipe_keeps_dependencies_and_drops_test_execution():
    script = "\n".join(
        [
            "COMMIT_HASH='abc123'",
            "uvx \\",
            "  -p 3.11 -w pytest==8.4.1 \\",
            "  -w git+https://example.org/model.git@${COMMIT_HASH} \\",
            "  pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA",
        ]
    )
    assert uv_recipe(script) == [
        "uvx",
        "-p",
        "3.11",
        "-w",
        "pytest==8.4.1",
        "-w",
        "git+https://example.org/model.git@abc123",
    ]
    assert uv_recipe("python -m pytest /tests/test_outputs.py") is None
    with pytest.raises(ValueError, match="unresolved"):
        uv_recipe("uvx -w git+https://example.org/repo@${UNKNOWN} pytest /tests/test.py")


def test_inventory_deduplicates_equal_dependencies_and_rejects_changed_sources(tmp_path):
    files = {}
    for task in ("first", "second"):
        script = tmp_path / f"tasks/{task}/tests/test.sh"
        script.parent.mkdir(parents=True)
        script.write_text("uvx -p 3.13 -w pytest==8.4.1 pytest /tests/test_outputs.py\n")
        files[script.relative_to(tmp_path).as_posix()] = hashlib.sha256(
            script.read_bytes()
        ).hexdigest()
    (tmp_path / "provenance.json").write_text(json.dumps({"revision": "fixed", "files": files}))
    result = recipe_inventory(tmp_path, "fixed")
    assert len(result["groups"]) == 1
    assert next(iter(result["groups"].values()))["tasks"] == ["first", "second"]
    script.write_text(script.read_text().replace("8.4.1", "8.4.2"))
    with pytest.raises(ValueError, match="source changed"):
        recipe_inventory(tmp_path, "fixed")
