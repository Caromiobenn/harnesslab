"""Aliyun E2B adapter with isolated credentials, resource pins and phase networking."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shlex

from e2b import AsyncSandbox, AsyncTemplate, Template
from harbor.environments.e2b import E2BEnvironment
from harbor.models.task.config import NetworkMode

from project_paths import inside, project_root
from sandbox_profile import benchmark_profile_file, load_profile


class InsufficientStorageError(ValueError):
    """A newly placed instance does not provide the declared task disk budget."""


MAX_STORAGE_PLACEMENTS = 8
PIP_CONSTRAINT_PATH = "/opt/benchmark-next-runtime/pip-constraints.txt"


def pip_constraints_text(values):
    if not isinstance(values, dict):
        raise ValueError("Dependency constraints must be exact package-version pairs")
    for name, version in values.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+!-]*", version):
            raise ValueError("Only exact package versions are allowed in runtime constraints")
    return "".join(name + "==" + version + "\n" for name, version in sorted(values.items()))


def network_update(mode, hosts=()):
    if mode == NetworkMode.PUBLIC or mode == "public":
        # An empty update does not explicitly clear previous deny rules.
        return {"allow_internet_access": True, "allow_out": [], "deny_out": []}
    if mode == NetworkMode.NO_NETWORK or mode == "no-network":
        return {"allow_internet_access": False, "allow_out": [], "deny_out": ["0.0.0.0/0"]}
    if not hosts:
        raise ValueError("An allowlist must contain at least one explicit host")
    return {"allow_internet_access": False, "allow_out": list(hosts), "deny_out": ["0.0.0.0/0"]}


def source_fingerprint(environment_dir, config):
    """Bind overrides to the exact definition and resources, including the verifier."""
    files = {}
    environment_dir = Path(environment_dir)
    if environment_dir.is_dir():
        for path in sorted(environment_dir.rglob("*")):
            if path.is_symlink():
                raise ValueError("Environment symlinks require explicit review")
            if path.is_file():
                with path.open("rb") as stream:
                    files[path.relative_to(environment_dir).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    descriptor = {"files": files, "image": config.docker_image,
                  "cpus": config.cpus, "memory_mb": config.memory_mb,
                  "storage_mb": config.storage_mb, "gpus": config.gpus,
                  "gpu_types": config.gpu_types}
    return hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()


class BenchmarkAliyunEnvironment(E2BEnvironment):
    @classmethod
    def preflight(cls):
        root = project_root()
        load_profile(root, benchmark_profile_file(root))

    def __init__(self, *args, profile_file=None,
                 image_map="configs/benchmark-images-next.json", **kwargs):
        self._root = project_root()
        self._profile_file = benchmark_profile_file(self._root, profile_file)
        self._profile = load_profile(self._root, self._profile_file)
        super().__init__(*args, **kwargs)
        if any((self.environment_dir / name).exists() for name in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")):
            raise ValueError("This Aliyun E2B backend has no multi-container implementation; use a verified compose-capable backend")
        self._source_fingerprint = source_fingerprint(self.environment_dir, self.task_env_config)
        runtime_path = self._root / "configs/benchmark-runtime-next.json"
        runtime = json.loads(runtime_path.read_text()).get("environments", {}) if runtime_path.exists() else {}
        adaptation = runtime.get(self._source_fingerprint, {})
        self._runtime_env = adaptation.get("env", {})
        self._pip_constraints = pip_constraints_text(adaptation.get("pip_constraints", {}))
        self._loopback_redirect = adaptation.get('loopback_port_redirect')
        self._http_cache = adaptation.get('http_cache')
        self._http_cache_ready = False
        self._apt_security_archive = adaptation.get('apt_security_archive')
        if self._apt_security_archive not in (None, 'bullseye'):
            raise ValueError('Only the verified Debian bullseye security archive is supported')
        if self._loopback_redirect:
            if self._loopback_redirect.get('from') != 5000 or self._loopback_redirect.get('to') != 15000:
                raise ValueError('Only the verified task-local port mapping is supported')
        mapping_path = inside(self._root, image_map)
        mappings = json.loads(mapping_path.read_text()).get("environments", {}) if mapping_path.exists() else {}
        override = mappings.get(self._source_fingerprint, {})
        if override.get("profile_domain") and override["profile_domain"] != self._profile.domain:
            raise ValueError("Mapped template belongs to a different regional endpoint")
        self._image_runtime = override.get("runtime") or {}
        self._cpu_affinity_core = None
        self._resource_adaptation = override.get('resource_adaptation')
        from benchmark_next_cpu import allocated_cpus
        self._allocated_cpus = allocated_cpus({'cpus': self._effective_cpus,
            'memory_mb': self._effective_memory_mb, 'resource_adaptation': self._resource_adaptation})
        if self._resource_adaptation and (self._image_runtime.get('cpu_affinity_limit') != 1
                or self._image_runtime.get('allocated_cpus') != self._allocated_cpus):
            raise ValueError('CPU adaptation lacks a verified template runtime')
        if self._image_runtime:
            # Preserve defaults observed from the newly built official image,
            # including inherited WORKDIR/HOME absent from a FROM-only Dockerfile.
            self._workdir = self.task_env_config.workdir or self._image_runtime["workdir"]
        if override.get("environment_migration") or override.get("source_mirror_tag"):
            raise ValueError("Legacy image reuse is disabled by the selected fresh-build policy")
        self._verifier_bootstrap = override.get("verifier_bootstrap")
        self._verifier_prepared = False
        if self._verifier_bootstrap not in (None, "tb21-uv095-py313"):
            raise ValueError("Unknown verifier dependency profile")
        self._image = override.get("image") or self.task_env_config.docker_image
        self._build_reference = override.get("build_reference") or self._image
        self._existing_template = override.get("template_id")
        if override and override.get("source_fingerprint", self._source_fingerprint) != self._source_fingerprint:
            raise ValueError("Image override source fingerprint mismatch")
        if self._image and override.get("image") and "@sha256:" not in self._image:
            raise ValueError("Custom images must use immutable digest references")
        if not self._image and not self._existing_template:
            raise ValueError("Task needs an image built from its Dockerfile; add an exact fingerprint mapping before running")
        identity = [self._profile.domain, self._source_fingerprint, self._image,
                    self._effective_cpus, self._effective_memory_mb, self._effective_storage_mb]
        self._template_name = self._existing_template or "bench-next-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]

    def _startup_env(self):
        defaults = {"HOME": self._image_runtime["home"]} if self._image_runtime else {}
        if self._image_runtime.get("path"):
            defaults["PATH"] = self._image_runtime["path"]
        if self._pip_constraints:
            defaults["PIP_CONSTRAINT"] = PIP_CONSTRAINT_PATH
        return {**defaults, **self._runtime_env, **super()._startup_env()}

    async def _does_template_exist(self):
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            endpoint = "/templates/" + self._existing_template if self._existing_template else "/templates"
            response = await client.get(self._profile.api_url + endpoint,
                                        headers={"X-API-KEY": self._profile.api_key})
            if self._existing_template and response.status_code == 404:
                raise ValueError("Mapped template is not visible in this Team")
            response.raise_for_status()
            rows = response.json()
            if self._existing_template:
                # Regional list responses stop at 100 entries. A registered ID
                # must be checked directly, including its latest build state.
                builds = rows.get('builds') or []
                if rows.get('templateID') != self._existing_template or not builds:
                    raise ValueError('Mapped template has no matching build history')
                latest_date = max(build['createdAt'] for build in builds)
                latest = [build for build in builds if build['createdAt'] == latest_date]
                if len(latest) != 1:
                    raise ValueError('Mapped template latest build is ambiguous')
                build = latest[0]
                if any(build.get(key) != rows.get(key) for key in ('cpuCount', 'memoryMB')):
                    raise ValueError('Mapped template build resources differ from allocation')
                rows = [{**rows, 'buildStatus': build['status']}]
            elif isinstance(rows, dict):
                rows = rows.get("templates", rows.get("data", []))
        matches = [row for row in rows if row.get("templateID") == self._template_name
                   or self._template_name in (row.get("aliases") or [])]
        if not matches:
            if self._existing_template:
                raise ValueError("Mapped template is not visible in this Team")
            return False
        if len(matches) != 1 or matches[0].get("buildStatus") != "ready":
            raise ValueError("Template alias exists but is not uniquely ready")
        row = matches[0]
        if row.get("cpuCount") != (self._allocated_cpus or 1) or row.get("memoryMB") != (self._effective_memory_mb or 2048):
            raise ValueError("Ready template CPU/memory differ from task requirements")
        return True

    async def _create_template(self):
        if self._existing_template:
            raise ValueError("An explicitly mapped template must already exist")
        if not self._image:
            raise ValueError("No reproducible task image")
        if "@sha256:" not in self._image:
            raise ValueError("Pin the task image digest in benchmark-images-next.json before building")
        await self._verify_build_reference()
        self._created_template_id = None
        def on_log(entry):
            message = str(entry)
            self.logger.info("Template build: %s", message)
            if match := re.search(r"Template created with ID: ([a-zA-Z0-9_-]+)", message):
                self._created_template_id = match[1]
        try:
            await AsyncTemplate.build(
                template=Template().from_image(self._build_reference), alias=self._template_name,
                cpu_count=int(self._allocated_cpus or 1), memory_mb=int(self._effective_memory_mb or 2048),
                min_free_disk_mb=int(self._effective_storage_mb or 10240),
                on_build_logs=on_log,
                **self._profile.client_kwargs())
            await self._verify_build_reference()
        except BaseException:
            # A failed template is owned by this deterministic alias. Retain the
            # error log; do not retry the build or switch to an older benchmark.
            await self._cleanup_failed_template()
            raise

    async def _verify_build_reference(self):
        if self._build_reference == self._image:
            return
        from pin_benchmark_next_image import public_image_digest
        actual = await asyncio.to_thread(public_image_digest, self._build_reference)
        if actual != self._image:
            raise ValueError("Image tag changed relative to the pinned manifest; refuse to build/use the result")

    async def _cleanup_failed_template(self):
        import httpx
        template_id = getattr(self, "_created_template_id", None)
        if not template_id:
            self.logger.warning("Build did not return an owned template ID; no template was deleted")
            return
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                headers = {"X-API-KEY": self._profile.api_key}
                result = await client.delete(self._profile.api_url + "/templates/" + template_id, headers=headers)
                if result.status_code != 404:
                    result.raise_for_status()
                self.logger.info("Removed unsuccessful owned template %s", template_id)
        except Exception as exc:
            self.logger.error("Failed-template cleanup could not be verified: %s", type(exc).__name__)

    async def _create_sandbox(self):
        for attempt in range(MAX_STORAGE_PLACEMENTS):
            try:
                await self._create_sandbox_once()
                return
            except InsufficientStorageError as exc:
                self.logger.warning("Storage placement attempt %s rejected: %s", attempt + 1, exc)
                from benchmark_next_cleanup import cleanup_run
                run_id = os.getenv("BENCHMARK_NEXT_RUN", self.session_id)
                cleanup = await asyncio.to_thread(cleanup_run, self._root, run_id,
                    profile_file=self._profile_file, expected_ids=[self._sandbox.sandbox_id])
                if not cleanup["verified"]:
                    raise RuntimeError("Insufficient-capacity instance cleanup is not verified") from exc
                self._sandbox = None
                if attempt == MAX_STORAGE_PLACEMENTS - 1:
                    raise
                await asyncio.sleep(2)

    async def _create_sandbox_once(self):
        policy = network_update(self.network_policy.network_mode, self.network_policy.allowed_hosts)
        internet = policy.pop("allow_internet_access")
        self._sandbox = await AsyncSandbox.create(
            template=self._template_name, timeout=self._sandbox_timeout,
            metadata={"environment_name": self.environment_name, "session_id": self.session_id,
                      "benchmark_framework": "next", "source_fingerprint": self._source_fingerprint,
                      "benchmark_next_run": os.getenv("BENCHMARK_NEXT_RUN", self.session_id)},
            envs=self._startup_env(), secure=True,
            allow_internet_access=internet, network=policy if any(policy.values()) else None,
            **self._profile.client_kwargs())
        self.logger.info("Created sandbox %s from %s for source %s",
                         self._sandbox.sandbox_id, self._template_name, self._source_fingerprint)
        # E2B command cwd must already exist; Docker's WORKDIR creation is not
        # reproduced when a prebuilt/template image is selected externally.
        if self._workdir:
            result = await self._sandbox.commands.run("mkdir -p -- " + shlex.quote(self._workdir),
                                                       cwd="/", user="root", timeout=30)
            if result.exit_code:
                raise RuntimeError("Could not create the declared working directory")
        if self._effective_storage_mb:
            result = await self._sandbox.commands.run("df -Pm / | awk 'NR==2 {print $4}'", user="root", timeout=30)
            if result.exit_code:
                raise RuntimeError("Could not inspect sandbox disk capacity")
            available = int(result.stdout.strip())
            self.logger.info("Sandbox %s has %s MiB available; task requires %s MiB",
                             self._sandbox.sandbox_id, available, self._effective_storage_mb)
            if available < self._effective_storage_mb:
                raise InsufficientStorageError(f"{self._sandbox.sandbox_id}: available={available} MiB, required={self._effective_storage_mb} MiB")
        if self._pip_constraints:
            result = await self._sandbox.commands.run("mkdir -p /opt/benchmark-next-runtime && printf %s " +
                shlex.quote(self._pip_constraints) + " > " + shlex.quote(PIP_CONSTRAINT_PATH), user="root", timeout=30)
            if result.exit_code:
                raise RuntimeError("Could not install the recorded dependency constraints")
        if self._apt_security_archive:
            command = r'''set -eu
. /etc/os-release
test "$VERSION_CODENAME" = bullseye
for file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  test -f "$file" || continue
  sed -i -E 's#https?://(deb|security)[.]debian[.]org/debian-security#https://archive.debian.org/debian-security#g' "$file"
done
'''
            result = await self._sandbox.commands.run(command, user='root', timeout=30)
            if result.exit_code:
                raise RuntimeError('Could not select the official Debian security archive')
            self.logger.info('Selected official Debian bullseye security archive; APT signature validation retained')
        if self._resource_adaptation:
            from benchmark_next_cpu import affinity_probe_command, parse_affinity_probe
            result = await self._sandbox.commands.run(affinity_probe_command(), user='root', timeout=30)
            if result.exit_code:
                raise RuntimeError('CPU affinity utility is unavailable')
            proof = parse_affinity_probe(result.stdout)
            self._cpu_affinity_core = proof['core']
            self.logger.info('Verified one-core task affinity: %s', json.dumps(proof, sort_keys=True))
        if self._loopback_redirect:
            artifact = self._loopback_redirect['artifact']
            helper = inside(self._root, artifact['path'])
            content = helper.read_bytes()
            if (hashlib.sha256(content).hexdigest() != artifact['sha256']
                    or hashlib.sha256((self._root / 'scripts/benchmark_loopback_redirect.c').read_bytes()).hexdigest() != artifact['source_sha256']):
                raise ValueError('Loopback helper differs from its validated source or binary')
            result = await self._sandbox.commands.run('mkdir -p /opt/benchmark-next-runtime', user='root', timeout=30)
            if result.exit_code:
                raise RuntimeError('Could not create runtime helper directory')
            await self._sandbox.files.write('/opt/benchmark-next-runtime/loopback.so', content)
            self.logger.info('Installed task-only loopback mapping 5000 -> 15000, helper sha256=%s', artifact['sha256'])
        if self._http_cache:
            from benchmark_next_http_cache import prepare_http_cache
            await prepare_http_cache(self._root, self, self._http_cache)
            self._http_cache_ready = True
    async def _dispatch_command(self, command, *, cwd, env, timeout_sec, user):
        import time
        from benchmark_next_command import oracle_handle
        if self._resource_adaptation:
            from benchmark_next_cpu import restrict_command
            if self._cpu_affinity_core is None:
                raise RuntimeError('CPU affinity was not verified before execution')
            command = restrict_command(command, self._cpu_affinity_core)
        started = time.monotonic()
        handle = await super()._dispatch_command(command, cwd=cwd, env=env, timeout_sec=timeout_sec, user=user)
        return oracle_handle(handle, self._sandbox.commands, command, timeout_sec, started, self.logger)

    async def exec(self, command, **kwargs):
        if self._http_cache_ready:
            kwargs['env'] = {**(kwargs.get('env') or {}), 'http_proxy': 'http://127.0.0.1:18080'}
        if self._loopback_redirect:
            env = dict(kwargs.get('env') or {})
            preload = '/opt/benchmark-next-runtime/loopback.so'
            if env.get('LD_PRELOAD'):
                preload = env['LD_PRELOAD'] + ':' + preload
            kwargs['env'] = {**env, 'LD_PRELOAD': preload,
                             'BENCHMARK_LOOPBACK_FROM': '5000', 'BENCHMARK_LOOPBACK_TO': '15000'}
        # FC envd starts a login shell, which resets PATH after applying envs.
        # Restore the image's declared path inside that shell before the command.
        path = (kwargs.get("env") or {}).get("PATH", self._startup_env().get("PATH"))
        if path is not None:
            command = "export PATH=" + shlex.quote(path) + "; " + command
        if self._image_runtime:
            # Explicit callers (e.g. agent installers) still choose their own user.
            if kwargs.get("user") is None and self.default_user is None:
                kwargs["user"] = self._image_runtime["user"]
            kwargs["env"] = {"HOME": self._startup_env()["HOME"], **(kwargs.get("env") or {})}
        if self._verifier_bootstrap and "/tests/test.sh" in command:
            if not self._verifier_prepared:
                from benchmark_next_bootstrap import prepare_tb21
                await prepare_tb21(self._root, self)
                self._verifier_prepared = True
            from benchmark_next_bootstrap import verifier_environment
            kwargs["env"] = {**(kwargs.pop("env", None) or {}), **verifier_environment()}
        return await super().exec(command, **kwargs)

    async def _apply_network_policy(self, network_policy):
        if self._sandbox is None:
            raise RuntimeError("Cannot apply network policy without a sandbox")
        await self._sandbox.update_network(network_update(network_policy.network_mode, network_policy.allowed_hosts))
