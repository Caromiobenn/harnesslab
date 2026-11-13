"""Serve pinned public verifier downloads while leaving official test scripts intact."""

from __future__ import annotations

import json
import shlex


def curl_wrapper(python: str, real_curl: str, downloads: dict, log_path: str) -> str:
    """Map exact cached URLs to verified local files; preserve curl's remaining arguments."""
    return f"""#!{python}
import hashlib,json,os,sys
from pathlib import Path
downloads={downloads!r}
args=sys.argv[1:]
for index,value in enumerate(args):
    if value not in downloads: continue
    artifact=downloads[value]
    path=Path(artifact['path'])
    with path.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=artifact['sha256']:
            raise RuntimeError('Cached public download checksum mismatch: '+value)
    args[index]=path.as_uri()
    with open({log_path!r},'a') as stream:
        stream.write(json.dumps({{'url':value,'path':str(path),'sha256':artifact['sha256']}})+'\\n')
os.execv({real_curl!r},[{real_curl!r},*args])
"""


async def prepare_verifier(environment, spec: dict, control: str, python: str) -> dict:
    """Install only recorded public prerequisites after the actor has submitted."""
    from benchmark_next_bootstrap import prepare_tb21, verifier_environment

    (environment._root / "cache/tmp").mkdir(parents=True, exist_ok=True)
    await prepare_tb21(environment._root, environment)
    for index, artifact in enumerate(spec["archives"]):
        target = control + f"/verifier-prerequisite-{index}.tar.gz"
        await environment.upload_archive(
            environment._root / artifact["archive"], artifact["sha256"], target
        )
        await environment.root_command("tar -xzf " + shlex.quote(target) + " -C /", timeout=300)
    if spec.get("install_command"):
        await environment.root_command(spec["install_command"], timeout=300)
    real_curl = (await environment.root_command("command -v curl")).stdout.strip()
    directory = control + "/verifier-bin"
    await environment.root_command("mkdir -p " + directory)
    await environment._sandbox.files.write(
        directory + "/curl",
        curl_wrapper(python, real_curl, spec["downloads"], control + "/cached-downloads.jsonl"),
    )
    await environment.root_command("chmod 755 " + directory + "/curl")
    env = {**verifier_environment(), **spec["env"]}
    shell_path = (await environment.root_command("printf '%s' \"$PATH\"")).stdout.strip()
    env["PATH"] = directory + ":" + shell_path
    await environment._sandbox.files.write(
        control + "/verifier-prerequisites.json", json.dumps(spec, sort_keys=True)
    )
    return env
