"""Opt-in transport/dependency preparation for the pinned TB 2.1 verifier."""
import json
import shlex

from agent_artifacts import upload_artifacts, verified_artifact

DIRECTORY = "/opt/benchmark-next-verifier"


async def prepare_tb21(root, environment):
    manifest = json.loads((root / "manifests/bootstrap-artifacts.json").read_text())
    names = ("uv-x86_64-unknown-linux-gnu.tar.gz", "python313.tar.gz")
    artifacts = {name: verified_artifact(root / "cache/bootstrap" / name, manifest[name]["sha256"]) for name in names}
    async def execute(command):
        result = await environment.exec(command=command, user="root", timeout_sec=120)
        if result.return_code:
            raise RuntimeError("Pinned verifier dependency setup failed: " + (result.stderr or "")[-1000:])
        return result
    await upload_artifacts(root, artifacts, DIRECTORY, environment.upload_file, execute)
    await execute(f"tar -xzf {DIRECTORY}/python313.tar.gz -C {DIRECTORY} && "
                  f"tar -xzf {DIRECTORY}/uv-x86_64-unknown-linux-gnu.tar.gz -C {DIRECTORY}")
    result = await execute(f"{DIRECTORY}/uv-x86_64-unknown-linux-gnu/uv --version")
    if not result.stdout.startswith("uv 0.9.5"):
        raise ValueError("TB 2.1 requires its declared uv 0.9.5, not a newer cached version")
    code = '''from pathlib import Path
paths = [Path('/etc/apt/sources.list'), *Path('/etc/apt/sources.list.d').glob('*.list'), *Path('/etc/apt/sources.list.d').glob('*.sources')]
for path in paths:
    if not path.is_file(): continue
    text = path.read_text()
    for scheme in ('http://', 'https://'):
        text = text.replace(scheme+'deb.debian.org/debian-security', 'https://mirrors.aliyun.com/debian-security')
        text = text.replace(scheme+'security.debian.org/debian-security', 'https://mirrors.aliyun.com/debian-security')
        text = text.replace(scheme+'deb.debian.org/debian', 'https://mirrors.aliyun.com/debian')
        text = text.replace(scheme+'archive.ubuntu.com/ubuntu', 'https://mirrors.aliyun.com/ubuntu')
        text = text.replace(scheme+'security.ubuntu.com/ubuntu', 'https://mirrors.aliyun.com/ubuntu')
    path.write_text(text)
Path('/etc/apt/apt.conf.d/99benchmark-network').write_text('Acquire::http::Timeout "30";\\nAcquire::https::Timeout "30";\\nAcquire::Retries "1";\\nAcquire::Languages "none";\\n')
'''
    await execute(f"{DIRECTORY}/python313/bin/python3.13 -c " + shlex.quote(code))
    # The official installer can use its supported download URL override.
    # Its requested uv release and the cached archive are the same version.
    await execute(f"nohup {DIRECTORY}/python313/bin/python3.13 -m http.server 18765 --bind 127.0.0.1 "
                  f"--directory {DIRECTORY} > {DIRECTORY}/http.log 2>&1 < /dev/null &")


def verifier_environment():
    return {"UV_DOWNLOAD_URL": "http://127.0.0.1:18765", "UV_PYTHON": DIRECTORY + "/python313/bin/python3.13",
            "UV_PYTHON_INSTALL_DIR": DIRECTORY + "/managed-python", "UV_INDEX_URL": "https://mirrors.aliyun.com/pypi/simple/"}
