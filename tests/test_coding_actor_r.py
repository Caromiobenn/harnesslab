import importlib.util
import io
import tarfile
from pathlib import Path

import pytest


@pytest.mark.parametrize("version,accepted", [("4.9", True), ("5.1", False), ("4.90", False)])
def test_cached_r_source_is_verified_from_package_metadata(tmp_path, version, accepted):
    spec = importlib.util.spec_from_file_location(
        "actor_r", Path(__file__).parents[1] / "scripts/prepare_coding_actor_r.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "bnlearn_4.9.tar.gz"
    data = f"Package: bnlearn\nVersion: {version}\nDescription: Public source.\n".encode()
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("bnlearn/DESCRIPTION")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    package = {"name": "bnlearn", "version": "4.9"}
    if accepted:
        assert module.verify_package(path, package)["bytes"] == path.stat().st_size
    else:
        with pytest.raises(ValueError, match="declared name or version"):
            module.verify_package(path, package)
