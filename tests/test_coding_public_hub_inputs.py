import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def builder():
    path = Path(__file__).parents[1] / "scripts/prepare_coding_public_hub_inputs.py"
    spec = importlib.util.spec_from_file_location("public_hub", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pinned_snapshot_and_alias_are_loadable_through_generated_paths(
    builder, tmp_path, monkeypatch
):
    monkeypatch.setattr(builder, "PREFIX", str(tmp_path))
    revision = "a" * 40
    snapshot = tmp_path / "hub/models--owner--model/snapshots" / revision
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")
    calls = []

    def download(repo, **kwargs):
        calls.append((repo, kwargs))
        return str(snapshot)

    monkeypatch.setitem(
        sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=download)
    )
    recipe = {
        "repositories": [
            {
                "repo_id": "owner/model",
                "repo_type": "model",
                "revision": revision,
                "files": ["config.json"],
                "aliases": ["model"],
            }
        ]
    }
    exec(builder.download_code(recipe), {})
    assert calls[0][1]["revision"] == revision
    assert (snapshot.parent.parent / "refs/main").read_text() == revision
    assert (tmp_path / "hub/models--model/snapshots" / revision / "config.json").read_text() == "{}"
    recipe["repositories"][0]["revision"] = "main"
    with pytest.raises(ValueError, match="full commit"):
        builder.download_code(recipe)


@pytest.mark.parametrize("task", ["count-dataset-tokens", "hf-model-inference"])
def test_probes_load_public_inputs_without_computing_task_answers(builder, task, monkeypatch):
    recipes = json.loads(
        (Path(__file__).parents[1] / "configs/coding-public-hub-inputs.json").read_text()
    )
    recipe = recipes["tasks"][task]
    seen = []

    class PublicModel:
        @staticmethod
        def from_pretrained(name):
            seen.append(("model", name))
            return object()

    def load_dataset(repo, config, **kwargs):
        seen.append(("dataset", repo, config, kwargs))
        return [object()]

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        types.SimpleNamespace(
            AutoTokenizer=PublicModel, AutoModelForSequenceClassification=PublicModel
        ),
    )
    monkeypatch.setitem(sys.modules, "datasets", types.SimpleNamespace(load_dataset=load_dataset))
    exec(builder.probe_code(recipe), {})
    assert seen
    if task == "count-dataset-tokens":
        assert {item[2] for item in seen if item[0] == "dataset"} == {"default", "metadata"}
        assert all("revision" not in item[3] for item in seen if item[0] == "dataset")
    else:
        assert ("model", "distilbert-base-uncased-finetuned-sst-2-english") in seen
