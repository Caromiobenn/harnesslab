# Full-task runtime prerequisites

The infrastructure importer now includes the dependency modules and public assets
referenced by the original Hong Kong runtime profiles. This adds the CIFAR public
dataset cache helper and its Python runtime, plus the existing loopback port mapping
for the HF inference task. The importer checks the source profile's SHA-256 before
copying each declared asset. Dataset and binary cache files remain ignored; their
hashes and source/helper code are versioned in the repository.

The public CIFAR cache serves the original dataset bytes. It does not supply an agent
answer or change the training workload. The loopback mapping preserves the official
Flask/verifier URLs while avoiding the provider's occupied port 5000. Network policy
still applies to the instance. Runtime upload scratch space is created before startup.

Package preparation uses the versioned certifi CA bundle for task images without
system CA certificates. APT HTTPS and package signatures remain verified. Package
archives are installed only in the verifier phase.

## Acceptance evidence

Jobs 1208047 and 1208048 verified the Ubuntu certificate path, HF loopback startup and
CIFAR cache startup in fresh instances. Each installed its curl dependency archive
with internet disabled; all three instances were confirmed deleted. The first job's
CIFAR attempt failed because its local upload directory did not yet exist. The
directory creation fix was tested and that task alone was retried in job 1208048.
An earlier launch, job 1208041, failed before instance creation because its profile
symlink resolved outside the isolated project; the ignored profile is now local.

These are runtime/package acceptance checks, not official task scores. They call no
model and do not execute reference solutions. The official empty/reference controls
remain a separate readiness step. The code passed 147 tests, Ruff and smoke validation.
The six-task model matrix continues on its unchanged, frozen source version.

Runtime acceptance receipts and archive checksums are recorded in
`artifacts/full-runtime-acceptance.json`. Raw preparation records remain under
`artifacts/coding-system-caches/tb21-system-runtime-accept-20261114/` and
`artifacts/coding-system-caches/tb21-runtime-caffe-accept-20261114/`.
