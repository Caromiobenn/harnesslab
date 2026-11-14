"""Serve pinned public verifier downloads while leaving official test scripts intact."""

from __future__ import annotations

import json


def archive_extract_code(archive: str, destination: str = "/") -> str:
    """Extract a hash-verified public archive with its links and executable modes."""
    return (
        "import tarfile\n"
        f"with tarfile.open({archive!r}, 'r:gz') as stream:\n"
        f"    stream.extractall({destination!r}, filter='fully_trusted')\n"
    )


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
    from benchmark_next_bootstrap import DIRECTORY, prepare_tb21, verifier_environment

    (environment._root / "cache/tmp").mkdir(parents=True, exist_ok=True)
    await prepare_tb21(environment._root, environment)
    for index, artifact in enumerate(spec["archives"]):
        target = control + f"/verifier-prerequisite-{index}.tar.gz"
        await environment.upload_archive(
            environment._root / artifact["archive"], artifact["sha256"], target
        )
        await environment.python_command(archive_extract_code(target), timeout=300)
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
    # uvx's explicit -p 3.13 overrides UV_PYTHON; expose the already-pinned
    # interpreter as a fallback while preserving the image's Python precedence.
    env["PATH"] = (
        directory
        + ":"
        + DIRECTORY
        + "/uv-x86_64-unknown-linux-gnu:"
        + shell_path
        + ":"
        + DIRECTORY
        + "/python313/bin"
    )
    if spec.get("python_downloads"):
        hooks = control + "/verifier-python"
        await environment.root_command("mkdir -p " + hooks)
        await environment._sandbox.files.write(
            hooks + "/sitecustomize.py",
            urllib_cache_hook(spec["python_downloads"], control + "/cached-python-downloads.jsonl"),
        )
        existing = (
            env.get("PYTHONPATH")
            or (await environment.root_command("printf '%s' \"$PYTHONPATH\"")).stdout.strip()
        )
        env["PYTHONPATH"] = hooks + (":" + existing if existing else "")
    await environment._sandbox.files.write(
        control + "/verifier-prerequisites.json", json.dumps(spec, sort_keys=True)
    )
    return env


def urllib_cache_hook(downloads: dict, log_path: str) -> str:
    """Serve exact public verifier URLs; all other urllib requests retain their behavior."""
    return f"""import email.message,hashlib,json,urllib.request,urllib.response
from pathlib import Path
_downloads={downloads!r}
_urlopen=urllib.request.urlopen
def _cached_urlopen(url,*args,**kwargs):
    address=url.full_url if isinstance(url,urllib.request.Request) else url
    method=url.get_method() if isinstance(url,urllib.request.Request) else 'GET'
    data=kwargs.get('data',args[0] if args else None)
    if address not in _downloads or method!='GET' or data is not None:
        return _urlopen(url,*args,**kwargs)
    artifact=_downloads[address];path=Path(artifact['path'])
    with path.open('rb') as stream:
        digest=hashlib.sha256()
        for chunk in iter(lambda:stream.read(1048576),b''):digest.update(chunk)
    if digest.hexdigest()!=artifact['sha256']:
        raise RuntimeError('Cached public verifier input checksum mismatch: '+address)
    headers=email.message.Message()
    headers['Content-Length']=str(path.stat().st_size)
    headers['Content-Type']='application/octet-stream'
    with open({log_path!r},'a') as stream:
        stream.write(json.dumps({{'url':address,'path':str(path),'sha256':artifact['sha256']}})+'\\n')
    return urllib.response.addinfourl(path.open('rb'),headers,address,200)
urllib.request.urlopen=_cached_urlopen
"""
