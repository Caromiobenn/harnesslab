"""Cache pinned CRAN sources and their public dependencies for explicit repository URLs."""

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
from harnesslab.coding.native_controls import public_cache

PREFIX = "/opt/harnesslab-public-r"
PART_SIZE = 16 * 1024 * 1024


def repository_code(recipe: dict) -> str:
    names = "c(" + ",".join(json.dumps(p["name"]) for p in recipe["packages"]) + ")"
    urls = "c(" + ",".join(json.dumps(p["url"]) for p in recipe["packages"]) + ")"
    versions = "c(" + ",".join(json.dumps(p["version"]) for p in recipe["packages"]) + ")"
    return f"""prefix <- {json.dumps(PREFIX)}
repo <- file.path(prefix, "repo", "src", "contrib")
dir.create(repo, recursive=TRUE, showWarnings=FALSE)
seeds <- {names}; urls <- {urls}; versions <- {versions}
cran <- "https://cloud.r-project.org"
options(timeout=180)
for (i in seq_along(seeds)) {{
  target <- file.path(repo, paste0(seeds[i], "_", versions[i], ".tar.gz"))
  download.file(urls[i], target, mode="wb", quiet=FALSE)
  temporary <- tempfile(); dir.create(temporary)
  untar(target, files=paste0(seeds[i], "/DESCRIPTION"), exdir=temporary)
  description <- read.dcf(file.path(temporary, seeds[i], "DESCRIPTION"))
  stopifnot(description[1,"Package"]==seeds[i], description[1,"Version"]==versions[i])
}}
tools::write_PACKAGES(repo, type="source")
pinned <- read.dcf(file.path(repo,"PACKAGES"))
rownames(pinned) <- pinned[,"Package"]
available <- available.packages(repos=cran)
fields <- union(colnames(available), colnames(pinned))
db <- matrix(NA_character_, nrow=nrow(available)+nrow(pinned), ncol=length(fields),
             dimnames=list(c(rownames(available),rownames(pinned)),fields))
db[seq_len(nrow(available)),colnames(available)] <- available
db[nrow(available)+seq_len(nrow(pinned)),colnames(pinned)] <- pinned
db <- db[!duplicated(rownames(db), fromLast=TRUE),,drop=FALSE]
dependencies <- tools::package_dependencies(seeds, db=db,
  which=c("Depends","Imports","LinkingTo"), recursive=TRUE)
needed <- unique(c(seeds,unlist(dependencies)))
base <- rownames(installed.packages(priority=c("base","recommended")))
needed <- setdiff(needed,c("R",base))
missing <- setdiff(needed,rownames(db))
stopifnot(length(missing)==0)
other <- setdiff(needed,seeds)
if (length(other)) {{
  fetched <- download.packages(other,destdir=repo,repos=cran,available=available,type="source")
  stopifnot(setequal(fetched[,1],other))
}}
tools::write_PACKAGES(repo,type="source")
installed <- read.dcf(file.path(repo,"PACKAGES"))
rownames(installed) <- installed[,"Package"]
stopifnot(all(needed %in% rownames(installed)))
write.table(installed[,c("Package","Version"),drop=FALSE],file.path(prefix,"packages.tsv"),
            quote=FALSE,row.names=FALSE,sep="\\t")
cat("CACHED_PACKAGES",nrow(installed),"\\n")
"""


def installation_probe(recipe: dict) -> str:
    lines = [
        "options(timeout=10)",
        "install.packages('remotes', repos='https://cloud.r-project.org/', quiet=TRUE)",
    ]
    for package in recipe["packages"]:
        name, version = json.dumps(package["name"]), json.dumps(package["version"])
        if package["name"] == "rstan":
            lines.extend(
                [
                    "Sys.setenv(MAKEFLAGS='-j2')",
                    "dir.create(path.expand('~/.R'),showWarnings=FALSE)",
                    "cat('CXX14FLAGS=-O3 -march=native -mtune=native -fPIC\\n',"
                    "file=path.expand('~/.R/Makevars'),append=TRUE)",
                ]
            )
        lines.extend(
            [
                f"remotes::install_version({name},version={version},"
                "repos='https://cloud.r-project.org/')",
                f"stopifnot(packageVersion({name})==package_version({version}))",
                f"library({name},character.only=TRUE)",
            ]
        )
    lines.append("cat('PINNED_R_SOURCES_INSTALLED_OFFLINE\\n')")
    return "\n".join(lines)


def transport_code(recipe: dict) -> str:
    return f'''import hashlib,json
from pathlib import Path
prefix=Path({PREFIX!r});repo=prefix/'repo/src/contrib';urls={{}};files={{}}
for path in repo.iterdir():
    if not path.is_file():continue
    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    with path.open('rb') as stream:md5=hashlib.file_digest(stream,'md5').hexdigest()
    files[path.name]={{'sha256':sha,'md5':md5,'bytes':path.stat().st_size}}
    urls['https://cloud.r-project.org/src/contrib/'+path.name]=str(path)
for package in {recipe["packages"]!r}:
    path=repo/(package['name']+'_'+package['version']+'.tar.gz')
    urls[package['url']]=str(path)
values=','.join(json.dumps(url)+'='+json.dumps(path) for url,path in urls.items())
digests=','.join(json.dumps(str(repo/name))+'='+json.dumps(item['md5'])
                 for name,item in files.items())
profile="""local({{
  cached <- c("""+values+""")
  expected <- c("""+digests+""")
  original <- utils::download.file
  transfer <- function(url, destfile, ...) {{
    if (!length(url) || length(url)!=length(destfile) || !all(url %in% names(cached)))
      return(original(url, destfile, ...))
    paths <- unname(cached[url])
    stopifnot(all(unname(tools::md5sum(paths))==unname(expected[paths])))
    stopifnot(all(file.copy(paths, destfile, overwrite=TRUE)))
    cat(paste(url, collapse='\\n'), '\\n',
        file={json.dumps(PREFIX + "/cache-hits.txt")}, append=TRUE)
    invisible(0L)
  }}
  namespace <- asNamespace('utils')
  unlockBinding('download.file', namespace)
  assign('download.file', transfer, envir=namespace)
  lockBinding('download.file', namespace)
}})
"""
(prefix/'profile.R').write_text(profile)
(prefix/'cache-hits.txt').write_text('')
(prefix/'files.json').write_text(json.dumps(files,sort_keys=True))
print(json.dumps({{'files':files,'urls':urls}}))
'''


async def prepare_one(root, dataset, run, task, recipe, ledger):
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import CONTROL, NativeStudyEnvironment

    source = dataset / "tasks" / task
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    system = public_cache(root, ledger["families"]["actor_system"][task])
    if system["source_fingerprint"] != fingerprint:
        raise ValueError("R build dependencies belong to a different task image")
    folder = root / "artifacts/coding-actor-r" / run / task
    if folder.exists():
        raise ValueError("Inspect the previous R source preparation before choosing a new run")
    profile = folder / "profile.json"
    entry = {
        "runtime_profile": "native",
        "source_fingerprint": fingerprint,
        "capture_paths": ["/app"],
        "archives": [system["archive"]],
        "env": system["env"],
    }
    save_json(profile, {"tasks": {task: entry}})
    identity = run + "-cran-" + task
    environment = NativeStudyEnvironment(
        environment_dir=source / "environment",
        environment_name=task,
        session_id=identity,
        trial_paths=TrialPaths(trial_dir=folder / "trial"),
        task_env_config=spec.environment,
        profile_file=".env.sandbox",
        image_map="configs/benchmark-images-next.json",
        sandbox_timeout_secs=7200,
        prerequisites_manifest=str(profile.relative_to(root)),
    )
    record = {
        "task": task,
        "recipe": recipe,
        "source_fingerprint": fingerprint,
        "benchmark_revision": ledger["benchmark_revision"],
        "model_calls": 0,
        "ok": False,
    }
    owned = set()
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        record["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(folder / "receipt.json", record)
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        install = "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get -y install "
        result = await environment.exec(
            install + shlex.join(recipe["system_packages"]),
            env=system["offline_env"],
            user="root",
            timeout_sec=600,
        )
        (folder / "system.stdout").write_text((result.stdout or "") + (result.stderr or ""))
        if result.return_code:
            raise RuntimeError("R source build dependencies did not install offline")
        ca = CONTROL + "/cran-ca.pem"
        await environment._sandbox.files.write(ca, Path(certifi.where()).read_bytes())
        await environment._sandbox.update_network({"allow_internet_access": True, "allow_out": []})
        code = repository_code(recipe)
        (folder / "download.R").write_text(code)
        await environment._sandbox.files.write("/tmp/prepare-cran.R", code)
        result = await environment.exec(
            "Rscript /tmp/prepare-cran.R",
            user="root",
            env={"CURL_CA_BUNDLE": ca, "SSL_CERT_FILE": ca},
            timeout_sec=1800,
        )
        (folder / "download.stdout").write_text(result.stdout or "")
        (folder / "download.stderr").write_text(result.stderr or "")
        if result.return_code:
            raise RuntimeError("Public CRAN source preparation failed")
        record["repository"] = json.loads(
            (await environment.python_command(transport_code(recipe))).stdout
        )
        save_json(folder / "receipt.json", record)
        code = installation_probe(recipe)
        (folder / "offline.R").write_text(code)
        await environment._sandbox.files.write("/tmp/probe-cran.R", code)
        await environment.root_command("mkdir -p /tmp/harnesslab-r-probe")
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        env = {"R_PROFILE_USER": PREFIX + "/profile.R"}
        result = await environment.exec(
            "Rscript /tmp/probe-cran.R",
            user="root",
            env={**env, "R_LIBS_USER": "/tmp/harnesslab-r-probe"},
            timeout_sec=3600,
        )
        (folder / "offline.stdout").write_text(result.stdout or "")
        (folder / "offline.stderr").write_text(result.stderr or "")
        if result.return_code:
            raise RuntimeError("Pinned R packages did not install and load offline")
        record["offline_probe"] = {"return_code": 0, "stdout": result.stdout[-2000:]}
        await environment._sandbox.files.write(PREFIX + "/cache-hits.txt", "")
        code = f"""import hashlib,json,tarfile
from pathlib import Path
archive=Path('/tmp/actor-r.tar.gz')
with tarfile.open(archive,'w:gz') as stream:stream.add({PREFIX!r},arcname={PREFIX.lstrip("/")!r})
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        part=str(archive)+'.part-'+str(len(parts));Path(part).write_bytes(data);parts.append(part)
with archive.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'sha256':sha,'bytes':archive.stat().st_size,'parts':parts}}))
"""
        info = json.loads((await environment.python_command(code, timeout=600)).stdout)
        archive = folder / "actor-r.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred CRAN archive changed")
        record.update(
            ok=True,
            env=env,
            offline_env={},
            archive={
                "archive": str(archive.relative_to(root)),
                "sha256": info["sha256"],
                "bytes": info["bytes"],
            },
        )
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if environment._sandbox:
            owned.add(environment._sandbox.sandbox_id)
            try:
                await environment.stop(delete=True)
            except Exception as exc:
                record["stop_error"] = type(exc).__name__
        record["cleanup"] = await asyncio.to_thread(
            cleanup_run, root, identity, profile_file=".env.sandbox", expected_ids=owned
        )
        save_json(folder / "receipt.json", record)
        print(
            json.dumps(
                {key: record.get(key) for key in ["task", "ok", "archive", "error", "cleanup"]}
            ),
            flush=True,
        )
    return record


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--cache-ledger", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short preparation run name")
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    profiles = json.loads((root / "configs/coding-actor-r.json").read_text())
    ledger = json.loads(args.cache_ledger.read_text())
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    if (
        profiles["benchmark_revision"] != ledger["benchmark_revision"]
        or profiles["benchmark_revision"] != provenance["revision"]
    ):
        raise ValueError("R source recipe belongs to another benchmark revision")
    results = [
        await prepare_one(root, args.dataset, args.run, task, profiles["tasks"][task], ledger)
        for task in args.tasks
    ]
    save_json(
        root / "artifacts/coding-actor-r" / args.run / "summary.json",
        {"model_calls": 0, "results": results},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
