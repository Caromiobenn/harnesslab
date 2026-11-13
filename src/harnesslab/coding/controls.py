"""Official reference and empty submissions for the shared task environment."""

from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.agents.oracle import OracleAgent
from harbor.models.trial.paths import TrialPaths


class EmptyControl(BaseAgent):
    @staticmethod
    def name():
        return "harnesslab-empty"

    def version(self):
        return "1"

    async def setup(self, environment):
        pass

    async def run(self, instruction, environment, context):
        pass


class OracleControl(OracleAgent):
    def __init__(self, logs_dir, task_dir, *args, **kwargs):
        super().__init__(
            *args,
            logs_dir=logs_dir,
            task_dir=Path(task_dir),
            trial_paths=TrialPaths(trial_dir=Path(logs_dir).parent),
            **kwargs,
        )
