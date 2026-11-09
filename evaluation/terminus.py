"""Final-only Terminus-2 with native task timeouts and per-stage call counts."""
import builtins
import dis
import itertools
import types

from harbor.agents.terminus_2.terminus_2 import Terminus2

UNBOUNDED_EPISODES = object()


def episode_loop(function):
    """Replace the inherited finite episode iterator in a local function copy."""
    instructions = list(dis.get_instructions(function))
    if sum(i.opname=='LOAD_GLOBAL' and i.argval=='range' for i in instructions)!=1 or not any(
            i.opname=='LOAD_ATTR' and i.argval=='_max_episodes' for i in instructions):
        raise RuntimeError('Unsupported Terminus-2 episode loop')

    def ranges(*args):
        return itertools.count() if args == (UNBOUNDED_EPISODES,) else builtins.range(*args)

    clone = types.FunctionType(function.__code__,dict(function.__globals__,range=ranges),
                               function.__name__,function.__defaults__,function.__closure__)
    clone.__kwdefaults__ = function.__kwdefaults__
    return clone


class CallMeter:
    def __init__(self, llm):
        self.llm = llm
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self.llm, name)

    async def call(self, *args, **kwargs):
        result = await self.llm.call(*args, **kwargs)
        self.calls += 1
        return result


class FinalTerminus2(Terminus2):
    def __init__(self, *args, **kwargs):
        kwargs['max_turns'] = None
        super().__init__(*args, **kwargs)
        self._meter = CallMeter(self._llm)
        self._llm = self._meter

    async def run(self, instruction, environment, context):
        self._meter.calls = 0
        try:
            await super().run(instruction, environment, context)
        finally:
            if context.metadata is None:
                context.metadata = {}
            context.metadata['resources'] = {'llm_calls': self._meter.calls}

    async def _run_agent_loop(self, *args, **kwargs):
        function = episode_loop(Terminus2._run_agent_loop)
        maximum = self._max_episodes
        self._max_episodes = UNBOUNDED_EPISODES
        try:
            return await function(self, *args, **kwargs)
        finally:
            self._max_episodes = maximum
