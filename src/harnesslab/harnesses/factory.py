"""Construct harness adapters from experiment configuration."""

from harnesslab.config import OpenAICompatibleModelSettings, VerificationSettings
from harnesslab.harnesses.base import AgentHarness
from harnesslab.harnesses.framework_agents import FrameworkAgentHarness
from harnesslab.harnesses.mock import MockHarness
from harnesslab.harnesses.online import ModelFactory, OnlineFrameworkAgentHarness
from harnesslab.models import HarnessKind


def build_harness(kind: HarnessKind, model_name: str) -> AgentHarness:
    if kind is HarnessKind.MOCK:
        return MockHarness(model_name=model_name)
    return FrameworkAgentHarness(kind=kind, model_name=model_name)


def build_online_harness(
    kind: HarnessKind,
    settings: OpenAICompatibleModelSettings,
    *,
    model_factory: ModelFactory | None = None,
    verification: VerificationSettings | None = None,
) -> AgentHarness:
    return OnlineFrameworkAgentHarness(
        kind=kind,
        settings=settings,
        model_factory=model_factory,
        verification=verification,
    )
