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


@pytest.mark.parametrize("shallow_tag", [False, True])
def test_public_history_and_pinned_tag_clones_work_offline(builder, tmp_path, shallow_tag):
    source = tmp_path / "source"
    env = dict(
        os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_ALLOW_PROTOCOL="file"
    )

    def git(*args):
        return subprocess.check_output(["git", *args], env=env, text=True).strip()

    git("init", str(source))
    for version in range(2):
        (source / "input.txt").write_text(f"Public input {version}")
        git("-C", str(source), "add", "input.txt")
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
    if shallow_tag:
        git(
            "-C",
            str(source),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "tag",
            "-a",
            "4.13.0",
            "-m",
            "Public release",
        )
    bare = tmp_path / "public.git"
    recipe = {
        "url": source.as_uri(),
        "revision": revision,
        "full_history": not shallow_tag,
        "required_paths": ["input.txt"],
    }
    if shallow_tag:
        recipe["tag"] = "4.13.0"
        recipe["tag_object"] = git("-C", str(source), "rev-parse", "refs/tags/4.13.0")
    subprocess.run(
        builder.download_command(recipe, str(bare)),
        shell=True,
        check=True,
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert (bare / "shallow").exists() == shallow_tag
    destination = tmp_path / "filtered-clone"
    probe = {**recipe, "url": "https://example.invalid/public.git"}
    result = subprocess.run(
        [sys.executable, "-c", builder.probe_code(probe, str(bare), str(destination))],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (
        '"tag_clone_verified": true' if shallow_tag else '"filtered_clone_verified": true'
    ) in result.stdout
    assert (destination / "input.txt").read_bytes() == (source / "input.txt").read_bytes()
    if shallow_tag:
        assert git("-C", str(destination), "rev-parse", "refs/tags/4.13.0") == git(
            "-C", str(source), "rev-parse", "refs/tags/4.13.0"
        )
        assert git("-C", str(destination), "rev-list", "--count", "HEAD") == "1"
    else:
        assert git("-C", str(destination), "rev-parse", "HEAD^") == git(
            "-C", str(source), "rev-parse", "HEAD^"
        )
