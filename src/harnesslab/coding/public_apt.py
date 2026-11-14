"""Replay pinned public repository metadata for an unchanged PPA command."""

from __future__ import annotations

import hashlib
from pathlib import Path


def repository_inputs(root: Path, recipes: list[dict]) -> list[dict]:
    inputs = []
    for recipe in recipes:
        path = root / recipe["source_file"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != recipe["sha256"]:
            raise ValueError("Public repository metadata checksum changed")
        if path.suffix != ".sources" or "Signed-By:" not in data.decode():
            raise ValueError("Use a signed Deb822 public source file")
        inputs.append(dict(recipe, filename=path.name, text=data.decode()))
    return inputs


def registration_wrapper(
    python: str,
    prefix: str,
    repositories: list[dict],
    real_command: str = "/usr/bin/add-apt-repository",
    sources_directory: str = "/etc/apt/sources.list.d",
    apt: str = "/usr/bin/apt-get",
) -> str:
    entries = {
        item["ppa"]: {key: item[key] for key in ["filename", "sha256"]} for item in repositories
    }
    return f"""#!{python}
import hashlib,json,os,subprocess,sys
from pathlib import Path
entries={entries!r}
args=sys.argv[1:]
if len(args)==2 and '-y' in args:
    ppa=args[1] if args[0]=='-y' else args[0]
    if ppa in entries:
        entry=entries[ppa]
        data=(Path({prefix!r})/'repositories'/entry['filename']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise ValueError('Cached public repository metadata changed')
        target=Path({sources_directory!r})/entry['filename']
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)
        with (Path({prefix!r})/'repository-hits.jsonl').open('a') as stream:
            stream.write(json.dumps({{'ppa':ppa,'sha256':entry['sha256']}})+'\\n')
        print('Using pinned public repository metadata for '+ppa,flush=True)
        raise SystemExit(subprocess.call([{apt!r},'update']))
os.execv({real_command!r},[{real_command!r},*args])
"""
