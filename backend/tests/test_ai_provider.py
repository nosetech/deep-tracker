import json
import subprocess

import pytest

from deep_tracker.ai import (
    AIError,
    AITimeoutError,
    AIUnavailableError,
    ClaudeCodeCLIProvider,
    RateLimitError,
    create_provider,
)
from deep_tracker.config.models import AISettings


def make(stdout="", returncode=0, stderr="", exc=None, calls=None):
    def runner(args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        if exc:
            raise exc
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    return ClaudeCodeCLIProvider(
        runner=runner, model="sonnet", env={"PATH": "/bin", "ANTHROPIC_API_KEY": "x"}
    )


def test_success_passes_args_and_stdin():
    calls = []
    out = json.dumps({"is_error": False, "result": "要約", "usage": {"output_tokens": 3}})
    r = make(out, calls=calls).generate("指示", system_prompt="sys", input_text="本文")
    assert r.text == "要約" and r.usage == {"output_tokens": 3}
    args, kw = calls[0]
    assert args[:2] == ["claude", "-p"] and "--tools" in args and "--model" in args
    assert args[args.index("--system-prompt") + 1] == "sys"
    assert kw["input"] == "本文"
    assert "ANTHROPIC_API_KEY" not in kw["env"]


def test_rate_limit():
    out = json.dumps(
        {
            "is_error": True,
            "api_error_status": 429,
            "result": "You've hit your session limit · resets 1pm (Asia/Tokyo)",
        }
    )
    with pytest.raises(RateLimitError) as e:
        make(out, returncode=1).generate("x")
    assert e.value.reset_text == "resets 1pm (Asia/Tokyo)"


def test_other_error_is_ai_error():
    out = json.dumps({"is_error": True, "api_error_status": 500, "result": "boom"})
    with pytest.raises(AIError) as e:
        make(out, returncode=1).generate("x")
    assert not isinstance(e.value, RateLimitError)


def test_timeout():
    with pytest.raises(AITimeoutError):
        make(exc=subprocess.TimeoutExpired("claude", 1)).generate("x")


def test_not_installed():
    with pytest.raises(AIUnavailableError):
        make(exc=FileNotFoundError()).generate("x")


def test_garbage_output():
    with pytest.raises(AIError):
        make("not json", returncode=1, stderr="oops").generate("x")


def test_factory():
    assert isinstance(create_provider(AISettings()), ClaudeCodeCLIProvider)


def test_factory_passes_command():
    p = create_provider(AISettings(command="/opt/bin/claude"))
    assert p._command == "/opt/bin/claude"


def test_missing_command_path_is_unavailable():
    with pytest.raises(AIUnavailableError, match="ai.command"):
        ClaudeCodeCLIProvider(command="/nonexistent/claude").generate("x")


@pytest.mark.cli
def test_real_cli():
    r = ClaudeCodeCLIProvider().generate("1+1は?数字のみ", system_prompt="簡潔に答える")
    assert "2" in r.text
