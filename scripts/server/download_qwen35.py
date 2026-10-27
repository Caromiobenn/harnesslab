"""Download from a reachable mirror, verifying against the pinned HF LFS hashes."""

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path("/mnt/harnesslab-data")
MODEL = ROOT / "models/Qwen3.5-9B"
METADATA = json.loads((ROOT / "runtime/model-file-metadata.json").read_text())
REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
assert METADATA["sha"] == REVISION


def download(item: dict) -> None:
    filename = item["rfilename"]
    target = MODEL / filename
    print("downloading", filename, flush=True)
    if not target.exists() or target.stat().st_size != item["lfs"]["size"]:
        subprocess.run(
            [
                "curl",
                "-4",
                "-fLsS",
                "--retry",
                "5",
                "--retry-delay",
                "5",
                "--connect-timeout",
                "20",
                "--continue-at",
                "-",
                f"https://modelscope.cn/models/Qwen/Qwen3.5-9B/resolve/master/{filename}",
                "-o",
                str(target),
            ],
            check=True,
        )
    digest = hashlib.file_digest(target.open("rb"), "sha256").hexdigest()
    expected = item["lfs"]["sha256"]
    if digest != expected:
        raise RuntimeError(f"pinned SHA-256 mismatch for {filename}: {digest} != {expected}")
    print("verified", filename, digest, flush=True)


if __name__ == "__main__":
    shards = [item for item in METADATA["siblings"] if item["rfilename"].endswith(".safetensors")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, shards))
    (MODEL / "REVISION").write_text(REVISION + "\n")
    hashes = []
    for path in sorted(MODEL.iterdir()):
        if path.is_file() and path.name not in {"SHA256SUMS", "REVISION"}:
            hashes.append(
                f"{hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()}  {path.name}"
            )
    (MODEL / "SHA256SUMS").write_text("\n".join(hashes) + "\n")
    print("ALL_SHARDS_VERIFIED", flush=True)
