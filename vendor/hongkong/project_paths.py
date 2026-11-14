"""HarnessLab-local paths for the reused Hong Kong adapter."""
import os
from pathlib import Path


def project_root(value=None):
    return Path(value or os.environ["HARNESSLAB_ROOT"]).resolve()


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path is outside HarnessLab")
    return path
