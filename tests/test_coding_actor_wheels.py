import importlib.util
import shlex
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def builder():
    path = Path(__file__).parents[1] / "scripts/prepare_coding_actor_wheels.py"
    spec = importlib.util.spec_from_file_location("actor_wheels", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_probe_is_valid_python_and_keeps_public_index_available(builder):
    # Probe Python executes the real import/version check without downloading anything.
    online, offline, env = builder.package_commands(
        "/image/bin/python", {"packages": ["pytest==8.4.1"], "import_modules": ["pytest"]}
    )
    assert "pip download" in online and "pip install" not in online
    assert "pip install pytest==8.4.1" in offline and "--no-index" not in offline
    assert env["PIP_FIND_LINKS"] == builder.PREFIX and "PIP_NO_INDEX" not in env
    command = shlex.split(offline.split(" && ", 1)[1])
    result = subprocess.run([sys.executable, *command[1:]], capture_output=True, text=True)
    assert result.returncode == 0 and '"pytest"' in result.stdout


def test_actor_cache_rejects_unpinned_requirements(builder):
    with pytest.raises(ValueError, match="version pins"):
        builder.package_commands("python", {"packages": ["grpcio"], "import_modules": ["grpc"]})
