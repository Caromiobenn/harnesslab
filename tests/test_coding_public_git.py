import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def builder():
    path = Path(__file__).parents[1] / "scripts/prepare_coding_public_git.py"
    spec = importlib.util.spec_from_file_location("public_git", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_git_clone_and_checkout_work_with_every_network_protocol_disabled(builder, tmp_path):
    source = tmp_path / "source"
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

    def git(*args):
        return subprocess.check_output(["git", *args], env=env, text=True).strip()

    git("init", str(source))
    (source / "README.md").write_text("Public source revision for an offline clone")
    git("-C", str(source), "add", "README.md")
    git(
        "-C",
        str(source),
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "public input",
    )
    revision = git("-C", str(source), "rev-parse", "HEAD")
    bare = tmp_path / "public.git"
    git("clone", "--bare", str(source), str(bare))
    recipe = {
        "url": "https://example.invalid/public",
        "aliases": ["https://example.invalid/public.git"],
        "revision": revision,
        "required_paths": ["README.md"],
    }
    for index, url in enumerate([recipe["url"], *recipe["aliases"]]):
        current = {
            **recipe,
            "url": url,
            "aliases": [other for other in [recipe["url"], *recipe["aliases"]] if other != url],
        }
        code = builder.probe_code(current, str(bare), str(tmp_path / f"clone-{index}"))
        result = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        assert '"offline_clone_verified": true' in result.stdout
        assert (tmp_path / f"clone-{index}" / "README.md").read_bytes() == (
            source / "README.md"
        ).read_bytes()


def test_public_git_input_rejects_a_moving_branch(builder):
    with pytest.raises(ValueError, match="full commit"):
        builder.download_command(
            {"revision": "main", "url": "https://example.invalid/public"}, "/cache"
        )
