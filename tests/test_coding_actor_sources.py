import importlib.util
from pathlib import Path


def test_binary_and_source_repository_generators_compile():
    path = Path(__file__).parents[1] / "scripts/prepare_coding_actor_system.py"
    spec = importlib.util.spec_from_file_location("actor_system", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for with_sources in (False, True):
        compile(
            module.repository_code("/opt/harnesslab-public-apt", with_sources),
            "apt-repository.py",
            "exec",
        )
