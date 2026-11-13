"""Load a complete sandbox connection without inheriting another Team's key."""
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
import json
import os
import re
from urllib.parse import urlsplit

from dotenv import dotenv_values


@dataclass(frozen=True)
class SandboxProfile:
    api_key: str = field(repr=False)
    api_url: str
    domain: str
    region: str
    team_id: str = ""

    def client_kwargs(self):
        return {"api_key": self.api_key, "api_url": self.api_url, "domain": self.domain}

    def public_summary(self):
        return {"api_url": self.api_url, "domain": self.domain, "region": self.region,
                "team_id": self.team_id or None, "api_key_configured": True}


def parse_profile(text):
    # Disable ${...} expansion so the old shell's credentials cannot fill gaps.
    values = dotenv_values(stream=StringIO(text), interpolate=False)
    required = ("E2B_API_KEY", "E2B_API_URL", "E2B_DOMAIN")
    if missing := [key for key in required if not values.get(key)]:
        raise ValueError("Missing sandbox settings: " + ", ".join(missing))
    key, api_url, domain = (values[name] for name in required)
    if not re.fullmatch(r"e2b_[A-Za-z0-9_-]+", key):
        raise ValueError("E2B_API_KEY must be the complete e2b_ API key from the new Team")
    match = re.fullmatch(r"([a-z]{2}(?:-[a-z]+)+-\d|cn-[a-z]+)\.(sandbox|e2b\.fc)\.aliyuncs\.com", domain)
    if not match:
        raise ValueError("E2B_DOMAIN must be an Aliyun sandbox regional domain")
    try:
        url = urlsplit(api_url)
        valid = (url.scheme == "https" and url.netloc == "api." + domain
                 and url.path in ("", "/") and not url.query and not url.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("E2B_API_URL must be HTTPS and match E2B_DOMAIN exactly")
    team_id = values.get("SANDBOX_TEAM_ID") or ""
    if team_id and not re.fullmatch(r"[A-Za-z0-9_-]+", team_id):
        raise ValueError("Invalid SANDBOX_TEAM_ID")
    return SandboxProfile(key, api_url.rstrip("/"), domain, match[1], team_id)


def load_profile(root, relative="configs/sandbox-next.env"):
    root = Path(root).resolve()
    candidate = root / relative
    path = candidate.resolve()
    if not path.is_relative_to(root) or candidate.absolute() != path:
        raise ValueError("Sandbox profile must be a regular file inside the project")
    if not path.is_file():
        raise ValueError("Create the selected sandbox profile using its regional Team's API key: " + str(relative))
    if path.stat().st_nlink != 1:
        raise ValueError("Sandbox profile must not be a shared hard link")
    return parse_profile(path.read_text(encoding="utf-8-sig"))


def benchmark_profile_file(root, explicit=None):
    """Use one complete regional profile for preflight, execution and cleanup."""
    if explicit:
        return explicit
    if selected := os.getenv("BENCHMARK_NEXT_SANDBOX_ENV"):
        return selected
    path = Path(root) / "configs/benchmarks-next.json"
    if path.is_file():
        return json.loads(path.read_text())["sandbox_profile"]
    # Diagnostic/unit-test roots without a benchmark catalog retain their profile.
    return "configs/sandbox-next.env"
