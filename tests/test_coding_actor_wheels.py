import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


@pytest.fixture
def builder():
    path = Path(__file__).parents[1] / "scripts/prepare_coding_actor_wheels.py"
    spec = importlib.util.spec_from_file_location("actor_wheels", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("system_python", [False, True])
def test_offline_probe_is_valid_python_and_keeps_public_index_available(builder, system_python):
    # Probe Python executes the real import/version check without downloading anything.
    online, offline, env = builder.package_commands(
        "/image/bin/python3",
        {
            "packages": ["pytest==8.4.1"],
            "import_modules": ["pytest"],
            "break_system_packages": system_python,
        },
    )
    assert "pip download" in online and "pip install" not in online
    assert "pip install pytest==8.4.1" in offline and "--no-index" not in offline
    assert env["PIP_FIND_LINKS"] == builder.PREFIX and "PIP_NO_INDEX" not in env
    assert ("--break-system-packages" in offline) == system_python
    assert "--break-system-packages" not in online
    command = shlex.split(offline.split(" && ", 1)[1])
    result = subprocess.run([sys.executable, *command[1:]], capture_output=True, text=True)
    assert result.returncode == 0 and '"pytest"' in result.stdout


def test_actor_cache_rejects_unpinned_requirements(builder):
    with pytest.raises(ValueError, match="version pins"):
        builder.package_commands("python", {"packages": ["grpcio"], "import_modules": ["grpc"]})


def test_secondary_python_probe_imports_its_isolated_install_target(builder, tmp_path):
    target = tmp_path / "secondary packages"
    target.mkdir()
    (target / "secondary_probe.py").write_text("value = 123\n")
    metadata = target / "secondary_probe-1.2.3.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: secondary-probe\nVersion: 1.2.3\n")
    _, offline, actor_env = builder.package_commands(
        sys.executable,
        {"packages": ["secondary-probe==1.2.3"], "import_modules": ["secondary_probe"]},
        probe_target=str(target),
    )
    install, check = offline.split(" && ", 1)
    args = shlex.split(install)
    assert args[args.index("--target") + 1] == str(target)
    assignment, *command = shlex.split(check)
    name, value = assignment.split("=", 1)
    result = subprocess.run(
        command, env=dict(os.environ, **{name: value}), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"secondary-probe": "1.2.3"}
    assert "PYTHONPATH" not in actor_env


def test_source_build_dependencies_are_downloaded_without_becoming_task_requirements(builder):
    recipe = {
        "packages": ["pytest==8.4.1"],
        "build_packages": ["setuptools==80.9.0", "wheel==0.45.1"],
        "import_modules": ["pytest"],
    }
    online, offline, _ = builder.package_commands("python", recipe)
    assert all(package in shlex.split(online) for package in recipe["build_packages"])
    assert all(package not in offline for package in recipe["build_packages"])
    command = shlex.split(offline.split(" && ", 1)[1])
    result = subprocess.run([sys.executable, *command[1:]], capture_output=True, text=True)
    assert result.returncode == 0 and list(json.loads(result.stdout)) == ["pytest"]
    with pytest.raises(ValueError, match="version pins"):
        builder.package_commands("python", dict(recipe, build_packages=["setuptools"]))


def test_cpu_wheel_index_is_used_only_during_public_cache_download(builder):
    online, offline, env = builder.package_commands(
        "python",
        {
            "packages": ["torch==2.7.0+cpu", "numpy==2.3.1"],
            "import_modules": ["torch", "numpy"],
            "extra_index_url": "https://download.pytorch.org/whl/cpu",
        },
    )
    args = shlex.split(online)
    assert args[args.index("--extra-index-url") + 1] == "https://download.pytorch.org/whl/cpu"
    assert "torch==2.7.0+cpu" in args and "torch==2.7.0+cpu" in offline
    assert "https://" not in offline and "PIP_INDEX_URL" not in env


def test_uv_script_cache_uses_fresh_probe_path_and_the_reference_dependency_metadata(builder):
    recipe = {
        "installer": "uv",
        "python": "3.13",
        "packages": ["pytest==8.4.1"],
        "import_modules": ["pytest"],
    }
    online, offline, env = builder.package_commands("uv", recipe)
    assert shlex.split(online)[-1] != shlex.split(offline)[-1]
    assert "--offline" not in shlex.split(online) and "--offline" in shlex.split(offline)
    assert env["UV_PYTHON"] == "3.13" and "UV_OFFLINE" not in env
    source = builder.uv_probe_source(recipe)
    metadata = "\n".join(
        line[2:] for line in source.splitlines() if line.startswith("# ") and "///" not in line
    )
    assert tomllib.loads(metadata) == {
        "requires-python": ">=3.13",
        "dependencies": recipe["packages"],
    }
    result = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "pytest" in json.loads(result.stdout)["packages"]
