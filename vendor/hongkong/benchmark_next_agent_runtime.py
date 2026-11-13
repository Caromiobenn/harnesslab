"""Supply pinned native-harness dependencies missing from minimal task images."""
import json
from pathlib import Path

from agent_artifacts import upload_artifacts, verified_artifact

DIRECTORY = "/opt/benchmark-next-agent-runtime"


async def prepare_runtime(root, environment, execute, family):
    manifest = json.loads((root / "configs/benchmark-agent-runtime.json").read_text())
    probe = await environment.exec(command="python3 -c 'import sys; assert sys.version_info >= (3, 9)'", user="root", timeout_sec=20)
    report = {"python": "python3", "portable_python": False}
    if probe.return_code:
        name = manifest["python_artifact"]
        artifact = verified_artifact(root / "cache/bootstrap" / name, manifest["python_sha256"])
        await upload_artifacts(root, {name: artifact}, DIRECTORY, environment.upload_file, execute)
        await execute(f"tar -xzf {DIRECTORY}/{name} -C {DIRECTORY}")
        report.update(python=DIRECTORY + "/python313/bin/python3.13", portable_python=True,
                      python_sha256=manifest["python_sha256"])
    if family == "codex":
        import certifi
        if certifi.__version__ != manifest["certifi_version"]:
            raise ValueError("Install the pinned controller certifi version for native Codex")
        artifact = verified_artifact(Path(certifi.where()), manifest["ca_sha256"])
        await upload_artifacts(root, {"cacert.pem": artifact}, DIRECTORY, environment.upload_file, execute)
        report.update(ca_file=DIRECTORY + "/cacert.pem", ca_sha256=manifest["ca_sha256"],
                      certifi_version=manifest["certifi_version"])
    return report
