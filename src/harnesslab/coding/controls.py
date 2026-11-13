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


class NativeEmptyControl(EmptyControl):
    def __init__(self, *args, network_mode, **kwargs):
        super().__init__(*args, **kwargs)
        self.network_mode = network_mode

    async def setup(self, environment):
        await environment.begin_actor(self.network_mode, self.logs_dir)

    async def run(self, instruction, environment, context):
        await environment.end_actor(self.logs_dir)


class NativeOracleControl(OracleControl):
    def __init__(self, *args, network_mode, **kwargs):
        super().__init__(*args, **kwargs)
        self.network_mode = network_mode

    async def setup(self, environment):
        await environment.begin_actor(self.network_mode, self.logs_dir)

    async def run(self, instruction, environment, context):
        try:
            await super().run(instruction, environment, context)
        finally:
            await environment.end_actor(self.logs_dir)
