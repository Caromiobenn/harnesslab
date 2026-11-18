"""Small OpenAI-compatible client for the local DashScope study."""

import contextlib
import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v4.1-flash-1017"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_env(path):
    values = {}
    for row in Path(path).read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = row.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if sep and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key):
            values[key] = value.strip().strip("\"'")
    return {**values, **os.environ}


class DeepSeek:
    def __init__(self, key, base_url, model):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".aliyuncs.com")
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Select the HTTPS Alibaba Cloud endpoint for this key.")
        self.key = key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.opener = build_opener(NoRedirect())

    @classmethod
    def from_env(cls, env_file, base_url=BASE_URL, model=MODEL):
        config = read_env(env_file)
        key = config.get("DASHSCOPE_API_KEY") or config.get("DEEPSEEK_API_KEY")
        if not key:
            raise ValueError("Missing DashScope API key.")
        return cls(key, base_url, model)

    def chat(self, messages, max_tokens=4096, thinking=False, **options):
        payload = dict(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            enable_thinking=thinking,
            **options,
        )
        request = Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
        )
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=65) as response:
                    body = json.load(response)
                if not body.get("choices"):
                    raise RuntimeError("Provider response had no choices")
                return body
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    error = {}
                    with contextlib.suppress(ValueError, AttributeError):
                        error = json.load(exc).get("error", {})
                    error_code = str(error.get("code", "")) if isinstance(error, dict) else ""
                    safe_code = (
                        error_code if re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", error_code) else ""
                    )
                    raise RuntimeError(f"DashScope HTTP {exc.code} {safe_code}".strip()) from None
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError("DashScope request timed out or was unreachable") from None
            time.sleep(2 ** (attempt + 1))
