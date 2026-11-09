"""Process-local Harbor hooks for the evaluation protocol."""
from harbor.cli.main import app
from evaluation.agents import install_ablation
from evaluation.continuous import install_continue_after_failure
from evaluation.terminus import FinalTerminus2


def install_terminal_guard():
    original = FinalTerminus2._handle_llm_interaction

    async def checked(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        for command in result[0]:
            if '\x00' in command.keystrokes or any(0xD800 <= ord(c) <= 0xDFFF for c in command.keystrokes):
                feedback = ('ERROR: Terminal command contains a NUL or an invalid Unicode surrogate. '
                            'Use printable shell text and represent these characters as literal escape sequences.')
                return ([], False, feedback, *result[3:])
        return result

    FinalTerminus2._handle_llm_interaction = checked


if __name__ == '__main__':
    install_terminal_guard()
    install_continue_after_failure()
    install_ablation()
    app()
