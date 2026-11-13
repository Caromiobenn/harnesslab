"""Small helpers for pinned packages and chunked sandbox uploads."""
import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import tempfile
import urllib.request
from urllib.parse import urlsplit


def load_manifest(root, agent):
    return json.loads((root / f'manifests/{agent}-provenance.json').read_text())


def digest(path, algorithm='sha256'):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).digest()


@dataclass(frozen=True)
class Artifact:
    path: Path
    sha256: str


def verified_artifact(path, expected):
    if digest(path).hex() != expected:
        raise ValueError('Artifact checksum mismatch: ' + str(path))
    return Artifact(path, expected)


def download_package(manifest, archive):
    archive.parent.mkdir(parents=True, exist_ok=True)
    candidate = archive
    if not archive.exists():
        url = urlsplit(manifest['tarball_url'])
        if url.scheme != 'https' or url.hostname != 'registry.npmjs.org':
            raise ValueError('Expected an official npm package URL')
        candidate = archive.with_suffix('.partial')
        with urllib.request.urlopen(manifest['tarball_url'], timeout=60) as response, candidate.open('wb') as stream:
            shutil.copyfileobj(response, stream)
    actual = 'sha512-' + base64.b64encode(digest(candidate, 'sha512')).decode()
    if actual != manifest['package_integrity']:
        raise ValueError('Package integrity mismatch: ' + str(candidate))
    if candidate != archive:
        candidate.replace(archive)


def extract_binary(package, member, destination, expected):
    if destination.exists():
        return verified_artifact(destination, expected)
    entry = package.getmember(member)
    if not entry.isfile():
        raise ValueError('Expected a regular binary file: ' + member)
    partial = destination.with_suffix('.partial')
    with package.extractfile(entry) as source, partial.open('wb') as stream:
        shutil.copyfileobj(source, stream)
    verified_artifact(partial, expected)
    partial.chmod(0o755)
    partial.replace(destination)
    return Artifact(destination, expected)


async def upload_artifacts(root, artifacts, directory, upload, execute):
    """Local files are already verified; compare remote hashes to those same pins."""
    await execute('mkdir -p ' + shlex.quote(directory))
    with tempfile.TemporaryDirectory(prefix='agent-upload-', dir=root / 'cache/tmp') as temp:
        part = Path(temp) / 'part'
        for name, artifact in artifacts.items():
            destination = directory + '/' + name
            parts = []
            with artifact.path.open('rb') as stream:
                while chunk := stream.read(8 * 1024 * 1024):
                    part.write_bytes(chunk)
                    target = destination + f'.part-{len(parts):04d}'
                    await upload(part, target)
                    parts.append(target)
            await execute('cat ' + shlex.join(parts) + ' > ' + shlex.quote(destination))
            result = await execute('sha256sum ' + shlex.quote(destination))
            if result.stdout.split()[0] != artifact.sha256:
                raise ValueError('Uploaded artifact checksum mismatch: ' + name)
            await execute('rm -f -- ' + shlex.join(parts))
