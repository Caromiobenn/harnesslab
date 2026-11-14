"""Public experiment settings and separately loaded inference credentials."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

Group = Literal[
    "mini", "deepagents_default", "generic_retry", "rubric_transcript", "rubric_evidence"
]


class CodingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benchmark: Literal["terminal-bench-2.1"]
    revision: str
    tasks: list[str]
    groups: list[Group] = ["mini", "deepagents_default"]
    thinking: Literal["enabled", "disabled"] = "enabled"
    reasoning_effort: Literal["low", "high", "max"] = "high"
    max_output_tokens: int = Field(default=32768, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    context_window_tokens: int | None = Field(default=None, gt=0)
    max_model_calls: int = Field(default=0, ge=0)
    network_mode: Literal["public", "offline"] = "public"
    prerequisites_manifest: str | None = None
    request_timeout: int = Field(default=240, gt=0)
    response_transport: Literal["non_streaming", "streaming"] = "non_streaming"
    command_timeout: int = Field(default=120, gt=0)
    concurrency: int = Field(default=2, ge=1, le=4)
    repeats: int = Field(default=1, ge=1)
    max_review_iterations: int = Field(default=3, ge=1)
    review_tool_max_chars: int = Field(default=0, ge=0)
    langsmith_tracing: bool = False
    purpose: str


def project_root() -> Path:
    return Path(os.environ.get("HARNESSLAB_ROOT", Path(__file__).resolve().parents[3])).resolve()


def configure_runtime(root: Path) -> None:
    (root / "cache/tmp").mkdir(parents=True, exist_ok=True)
    os.environ["HARNESSLAB_ROOT"] = str(root)
    os.environ["DATA_ENGINEERING_ROOT"] = str(root)
    os.environ["BENCHMARK_NEXT_SANDBOX_ENV"] = ".env.sandbox"
    for key, relative in {
        "TMPDIR": "artifacts/tmp",
        "XDG_CACHE_HOME": "artifacts/cache/xdg",
        "UV_CACHE_DIR": "artifacts/cache/uv",
        "HF_HOME": "artifacts/cache/huggingface",
        "MSWEA_GLOBAL_CONFIG_DIR": "artifacts/mini-config",
    }.items():
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ.update(
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        MSWEA_CONFIGURED="true",
        MSWEA_SILENT_STARTUP="1",
        MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    vendor = str(root / "vendor/hongkong")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def load_config(root: Path, path: Path | None = None) -> CodingConfig:
    return CodingConfig.model_validate_json(
        (root / (path or "configs/coding-tb21.json")).read_text()
    )


def sampling_options(config: CodingConfig) -> dict:
    return {
        key: value
        for key in ("temperature", "top_p")
        if (value := getattr(config, key)) is not None
    }


def model_settings(root: Path, *, require_key: bool = True) -> dict[str, str]:
    # This project has one explicit inference profile; no old server credentials are inherited.
    values = dotenv_values(root / ".env", interpolate=False)
    key = values.get("DEEPSEEK_API_KEY") or ""
    if require_key and not key.strip():
        raise ValueError(f"Fill DEEPSEEK_API_KEY in {root / '.env'}")
    return {
        "api_key": key,
        "model": values.get("DEEPSEEK_MODEL") or "deepseek-flash",
        "base_url": values.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
        "api_style": values.get("DEEPSEEK_API_STYLE") or "deepseek",
    }


def thinking_body(config: CodingConfig, settings: dict[str, str]) -> dict:
    if settings["api_style"] == "aliyun":
        return {"enable_thinking": config.thinking == "enabled"}
    if settings["api_style"] == "deepseek":
        return {"thinking": {"type": config.thinking}}
    raise ValueError("DEEPSEEK_API_STYLE must be deepseek or aliyun")


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")
    temporary.replace(path)
