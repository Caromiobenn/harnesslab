import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def builder(monkeypatch):
    scripts = Path(__file__).parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "custom_verifier_builder", scripts / "prepare_coding_custom_verifier_caches.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "script,expected",
    [
        (
            "pip install pytest==8.4.1 requests==2.32.5\npytest /tests/test_outputs.py",
            {"kind": "pip", "packages": ["pytest==8.4.1", "requests==2.32.5"], "install_flags": []},
        ),
        (
            "pip install pytest==8.4.1 --break-system-packages",
            {
                "kind": "pip",
                "packages": ["pytest==8.4.1"],
                "install_flags": ["--break-system-packages"],
            },
        ),
        (
            "uv venv -p 3.12 .tb\nuv pip install pytest==8.4.1 mailman==3.3.8",
            {
                "kind": "uv-venv",
                "packages": ["pytest==8.4.1", "mailman==3.3.8"],
                "install_flags": [],
                "python": "3.12",
            },
        ),
    ],
)
def test_official_requirement_forms_preserve_pins_and_python_selection(builder, script, expected):
    assert builder.requirements(script) == expected


@pytest.mark.parametrize(
    "script",
    [
        "pip install pytest requests==2.32.5",
        "pip install pytest==8.4.1\npip install requests==2.32.5",
    ],
)
def test_unpinned_or_ambiguous_installations_need_explicit_recipe(builder, script):
    with pytest.raises(ValueError):
        builder.requirements(script)
