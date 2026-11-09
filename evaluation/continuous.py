"""Continuous Terminus-2 sessions for requirement-change measurements.

Only explicitly selected runs use this adapter. Native per-stage verification
and artifact collection remain unchanged; no verifier feedback is sent to LLM.
"""
import copy
from harbor.agents.capabilities import AgentCapabilities
from evaluation.terminus import FinalTerminus2


class ContinuousTerminus2(FinalTerminus2):
    capabilities = AgentCapabilities(atif=True, resume=True)

    async def run(self, instruction, environment, context):
        if not getattr(self, '_continuing', False):
            self._requirement_history = []
            self._terminal_restarted_for_step = False
        self._requirement_history.append(instruction)
        try:
            await super().run(instruction, environment, context)
        finally:
            # Per-stage metadata must not reference the mutable session history.
            if getattr(context, 'metadata', None) and 'all_messages' in context.metadata:
                context.metadata['all_messages'] = copy.deepcopy(context.metadata['all_messages'])
            if getattr(context, 'metadata', None) is not None:
                context.metadata['terminal_session_restarted'] = getattr(self, '_terminal_restarted_for_step', False)
            self._continuing = False

    async def resume(self, instruction, environment, context):
        if getattr(self, '_chat', None) is None:
            raise RuntimeError('Cannot resume without the previous Chat session')
        # An earlier agent command may have exited its interactive shell. A
        # new user turn must still reach the LLM, in the same surviving workspace.
        # Terminus2.setup only establishes TmuxSession; it does not reset Chat,
        # recreate the container, or replace any submitted code.
        session = getattr(self, '_session', None)
        self._terminal_restarted_for_step = session is None or not await session.is_session_alive()
        if self._terminal_restarted_for_step:
            await self.setup(environment)
        self._carried_chat = self._chat
        self._continuing = True
        try:
            await self.run(instruction, environment, context)
        finally:
            self._carried_chat = None

    async def _run_agent_loop(self, initial_prompt, chat, original_instruction=''):
        carried = getattr(self, '_carried_chat', None)
        if carried is not None:
            self._chat = chat = carried
        # Compaction must preserve the requirement history, including reversals.
        history = getattr(self, '_requirement_history', [original_instruction])
        contract = '\n\n'.join(
            f'User requirement stage {i} (later changes supersede earlier conflicts):\n{text}'
            for i, text in enumerate(history, 1))
        return await super()._run_agent_loop(initial_prompt, chat, contract)


def install_continue_after_failure():
    """Apply only in this explicitly configured worker process, not site-packages."""
    from harbor.trial.multi_step import MultiStepTrial
    def continue_after_step(self, step, step_result):
        if step.min_reward is not None:
            raise ValueError('Continuous experiments prohibit min_reward gates')
        return False
    MultiStepTrial._should_stop_after_step = continue_after_step
