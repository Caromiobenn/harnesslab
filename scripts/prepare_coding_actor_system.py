"""Cache public system installers without pre-installing actor task dependencies."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shlex
from pathlib import Path

import certifi

from harnesslab.coding.config import configure_runtime, project_root, save_json

PREFIX = "/opt/harnesslab-public-apt"
PART_SIZE = 16 * 1024 * 1024
REVISION = "12b7565679ce5006230b820666353673a133db93"


def repository_code(prefix: str, with_sources: bool = False) -> str:
    """Build APT's normal file repository; preserve public sources in the online arm."""
    return f"""import hashlib,json,shutil,subprocess
from pathlib import Path
prefix=Path({prefix!r});repo=prefix/'repo';entries=[];files={{}}
for path in sorted((repo/'debs').glob('*.deb')):
    data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
    metadata=subprocess.check_output(['dpkg-deb','-f',str(path)],text=True).rstrip()
    entry=metadata+'\\nFilename: debs/'+path.name+'\\nSize: '+str(len(data))
    entries.append(entry+'\\nSHA256: '+sha+'\\n')
    files[path.name]={{'sha256':sha,'bytes':len(data)}}
(repo/'Packages').write_text('\\n'.join(entries))
(prefix/'public-sources.d').mkdir(exist_ok=True)
(prefix/'empty-sources.d').mkdir(exist_ok=True)
original=Path('/etc/apt/sources.list')
local='deb [trusted=yes] file:'+str(repo)+' ./\\n'
source_index=None
if {with_sources!r}:
    sources=subprocess.check_output(['dpkg-scansources','sources'],cwd=repo,text=True)
    (repo/'Sources').write_text(sources)
    source_index=hashlib.sha256(sources.encode()).hexdigest()
    local+='deb-src [trusted=yes] file:'+str(repo)+' ./\\n'
(prefix/'public-sources.list').write_text(local+(original.read_text() if original.exists() else ''))
for path in Path('/etc/apt/sources.list.d').glob('*'):
    if path.is_file() and path.suffix in ('.list','.sources'):
        shutil.copy2(path,prefix/'public-sources.d'/path.name)
(prefix/'offline-sources.list').write_text(local)
modes=[('public','public-sources.list','public-sources.d'),
       ('offline','offline-sources.list','empty-sources.d')]
for mode,sources,parts in modes:
    configuration={{'Dir::Etc::sourcelist':str(prefix/sources),'Dir::Etc::sourceparts':str(prefix/parts),
                   'Acquire::Retries':'0','Acquire::http::Timeout':'10','Acquire::https::Timeout':'10'}}
    text='\\n'.join(key+' "'+value+'";' for key,value in configuration.items())+'\\n'
    (prefix/('apt-'+mode+'.conf')).write_text(text)
print(json.dumps({{'packages':files,'index_sha256':hashlib.sha256((repo/'Packages').read_bytes()).hexdigest(),
                  'source_index_sha256':source_index}}))
"""


async def prepare_one(
    root: Path,
    dataset: Path,
    run: str,
    name: str,
    packages: list[str],
    source_packages: list[str] | None = None,
    download_timeout_sec: int = 600,
    preserve_sudo_apt_config: bool = False,
) -> dict:
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import NativeStudyEnvironment

    source_packages = source_packages or []
    source = dataset / "tasks" / name
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    folder = root / "artifacts/coding-actor-system" / run / name
    receipt = folder / "receipt.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if (
            saved["packages"] == packages
            and saved.get("source_packages", []) == source_packages
            and saved.get("preserve_sudo_apt_config", False) == preserve_sudo_apt_config
            and saved["source_fingerprint"] == fingerprint
            and saved["ok"]
            and saved["cleanup"]["verified"]
        ):
            with (root / saved["archive"]["archive"]).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == saved["archive"]["sha256"]:
                    return saved
        raise ValueError("Inspect previous system cache preparation before a new run")
    profile = folder / "profile.json"
    save_json(
        profile,
        {
            "tasks": {
                name: {
                    "runtime_profile": "native",
                    "source_fingerprint": fingerprint,
                    "capture_paths": ["/app"],
                    "archives": [],
                }
            }
        },
    )
    identity = run + "-system-" + name
    environment = NativeStudyEnvironment(
        environment_dir=source / "environment",
        environment_name=name,
        session_id=identity,
        trial_paths=TrialPaths(trial_dir=folder / "trial"),
        task_env_config=spec.environment,
        profile_file=".env.sandbox",
        image_map="configs/benchmark-images-next.json",
        sandbox_timeout_secs=download_timeout_sec + 1200,
        prerequisites_manifest=str(profile.relative_to(root)),
    )
    result = {
        "task": name,
        "source_fingerprint": fingerprint,
        "packages": packages,
        "source_packages": source_packages,
        "download_timeout_sec": download_timeout_sec,
        "preserve_sudo_apt_config": preserve_sudo_apt_config,
        "ok": False,
        "model_calls": 0,
    }
    owned = set()
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        result["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(receipt, result)
        ca_path = "/opt/harnesslab-controller/preparation-ca.pem"
        ca_bundle = Path(certifi.where()).read_bytes()
        await environment._sandbox.files.write(ca_path, ca_bundle)
        result["preparation_ca"] = {
            "certifi_version": certifi.__version__,
            "sha256": hashlib.sha256(ca_bundle).hexdigest(),
        }
        apt = "apt-get -o Acquire::https::CaInfo=" + shlex.quote(ca_path)
        command = (
            f"mkdir -p {PREFIX}/repo/debs/partial && {apt} update -qq && "
            f"{apt} -y --download-only -o Dir::Cache::archives={PREFIX}/repo/debs install "
            + shlex.join(packages)
        )
        (folder / "prepare.sh").write_text(command + "\n")
        output = await environment.exec(command, user="root", timeout_sec=download_timeout_sec)
        (folder / "prepare.stdout").write_text(output.stdout or "")
        (folder / "prepare.stderr").write_text(output.stderr or "")
        if output.return_code:
            raise RuntimeError("System package download failed; see preparation logs")
        if source_packages:
            await environment.root_command(
                apt + " install -y --no-install-recommends dpkg-dev", timeout=300
            )
            await environment._sandbox.files.write(
                PREFIX + "/source-preparation.list",
                "deb-src http://deb.debian.org/debian trixie main\n",
            )
            source_apt = (
                apt
                + " -o Dir::Etc::sourcelist="
                + PREFIX
                + "/source-preparation.list -o Dir::Etc::sourceparts=-"
            )
            source_command = (
                f"mkdir -p {PREFIX}/repo/sources && {source_apt} update -qq && "
                f"cd {PREFIX}/repo/sources && {source_apt} source --download-only "
                + shlex.join(source_packages)
            )
            (folder / "source-prepare.sh").write_text(source_command + "\n")
            source_result = await environment.exec(source_command, user="root", timeout_sec=600)
            (folder / "source-prepare.stdout").write_text(source_result.stdout or "")
            (folder / "source-prepare.stderr").write_text(source_result.stderr or "")
            if source_result.return_code:
                raise RuntimeError("Public Debian source download failed")
        repository = await environment.python_command(
            repository_code(PREFIX, bool(source_packages)), timeout=120
        )
        result["repository"] = json.loads(repository.stdout)
        env = {"APT_CONFIG": PREFIX + "/apt-public.conf"}
        offline_env = {"APT_CONFIG": PREFIX + "/apt-offline.conf"}
        if preserve_sudo_apt_config:
            await environment.python_command(
                "from pathlib import Path\n"
                "path=Path('/etc/sudoers.d/harnesslab-public-apt')\n"
                "path.write_text('Defaults env_keep += \\\"APT_CONFIG\\\"\\n')\n"
                "path.chmod(0o440)\n"
            )
            await environment.root_command("visudo -cf /etc/sudoers.d/harnesslab-public-apt")
        apt_command = "sudo apt-get" if preserve_sudo_apt_config else "apt-get"
        install = (
            apt_command
            + " update -qq && DEBIAN_FRONTEND=noninteractive "
            + apt_command
            + " -y install "
            + shlex.join(packages)
        )
        if source_packages:
            install += (
                " && mkdir -p /tmp/offline-source-probe && cd /tmp/offline-source-probe"
                " && apt-get source --download-only " + shlex.join(source_packages)
            )
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        offline = await environment.exec(install, env=offline_env, user="root", timeout_sec=600)
        (folder / "offline.stdout").write_text(offline.stdout or "")
        (folder / "offline.stderr").write_text(offline.stderr or "")
        if offline.return_code:
            raise RuntimeError("Cached packages could not be installed offline")
        versions = await environment.root_command(
            "dpkg-query -W -f='${Package}=${Version}\\n' "
            + shlex.join(package.partition("=")[0] for package in packages)
        )
        result["offline_probe"] = {"return_code": offline.return_code, "versions": versions.stdout}
        code = f"""import hashlib,json,subprocess,tarfile
from pathlib import Path
prefix=Path({PREFIX!r});files={{}}
for path in sorted((prefix/'repo/debs').glob('*.deb')):
    with path.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
    files[path.name]={{'sha256':digest,'bytes':path.stat().st_size,
        'metadata':subprocess.check_output(['dpkg-deb','-f',str(path)],text=True)}}
for path in sorted((prefix/'repo/sources').glob('*')):
    if path.is_file():
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        files['sources/'+path.name]={{'sha256':digest,'bytes':path.stat().st_size}}
(prefix/'files.json').write_text(json.dumps(files,sort_keys=True))
indexes={{}}
for path in Path('/var/lib/apt/lists').glob('*harnesslab-public-apt*'):
    if path.is_file():
        with path.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
        indexes[str(path)]={{'sha256':digest,'bytes':path.stat().st_size}}
archive=Path('/tmp/verifier-system.tar.gz')
with tarfile.open(archive,'w:gz') as stream:
    for name in ['repo','public-sources.list','public-sources.d','offline-sources.list',
                 'empty-sources.d','apt-public.conf','apt-offline.conf','files.json']:
        stream.add(prefix/name,arcname=str(prefix/name).lstrip('/'))
    for name in indexes:
        stream.add(name,arcname=name.lstrip('/'))
    if {preserve_sudo_apt_config!r}:
        stream.add('/etc/sudoers.d/harnesslab-public-apt',
                   arcname='etc/sudoers.d/harnesslab-public-apt')
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        part=str(archive)+'.part-'+str(len(parts));Path(part).write_bytes(data);parts.append(part)
with archive.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'parts':parts,'files':files,'indexes':indexes,
                  'sha256':digest,'bytes':archive.stat().st_size}}))
"""
        info = json.loads((await environment.python_command(code, timeout=300)).stdout)
        archive = folder / "system.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred system cache checksum mismatch")
        result.update(
            ok=True,
            archive={
                "archive": str(archive.relative_to(root)),
                "sha256": info["sha256"],
                "bytes": info["bytes"],
            },
            files=info["files"],
            apt_indexes=info["indexes"],
            env=env,
            offline_env=offline_env,
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if environment._sandbox:
            owned.add(environment._sandbox.sandbox_id)
            try:
                await environment.stop(delete=True)
            except Exception as exc:
                result["stop_error"] = type(exc).__name__
        result["cleanup"] = await asyncio.to_thread(
            cleanup_run, root, identity, profile_file=".env.sandbox", expected_ids=owned
        )
        save_json(receipt, result)
        print(
            json.dumps(
                {
                    key: result.get(key)
                    for key in ("task", "ok", "archive", "offline_probe", "error", "cleanup")
                }
            ),
            flush=True,
        )
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short preparation run name")
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    if provenance["revision"] != REVISION:
        raise ValueError("System cache source revision differs from the study")
    for name in args.tasks:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]+", name):
            raise ValueError("Use dataset task names")
        relative = "tasks/" + name + "/tests/test.sh"
        if (
            hashlib.sha256((args.dataset / relative).read_bytes()).hexdigest()
            != provenance["files"][relative]
        ):
            raise ValueError("Official verifier source changed: " + name)
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    profiles = json.loads((root / "configs/coding-actor-system.json").read_text())
    if profiles["benchmark_revision"] != REVISION:
        raise ValueError("Actor package profiles belong to a different revision")
    gate = asyncio.Semaphore(2)

    async def one(name):
        async with gate:
            return await prepare_one(
                root,
                args.dataset,
                args.run,
                name,
                profiles["tasks"][name]["packages"],
                profiles["tasks"][name].get("source_packages"),
                profiles["tasks"][name].get("download_timeout_sec", 600),
                profiles["tasks"][name].get("preserve_sudo_apt_config", False),
            )

    results = await asyncio.gather(*(one(name) for name in args.tasks))
    save_json(
        root / "artifacts/coding-actor-system" / args.run / "summary.json",
        {"model_calls": 0, "revision": REVISION, "results": results},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
