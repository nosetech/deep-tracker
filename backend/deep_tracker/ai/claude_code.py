import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable

from deep_tracker.ai.base import (
    AIError,
    AIProvider,
    AIResult,
    AITimeoutError,
    AIUnavailableError,
    RateLimitError,
)

# サブスクリプション経路を確実にするため、子プロセスへ渡さない環境変数
_STRIPPED_ENV = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
_RESET_PATTERN = re.compile(r"resets?\s+.+$", re.IGNORECASE)

Runner = Callable[..., subprocess.CompletedProcess]


def parse_reset_text(message: str) -> str | None:
    match = _RESET_PATTERN.search(message)
    return match.group(0).strip() if match else None


class ClaudeCodeCLIProvider(AIProvider):
    """`claude -p` をワンショットで実行する。ツールは全て無効化し、権限フラグは使わない。"""

    def __init__(
        self,
        *,
        command: str = "claude",
        model: str | None = None,
        timeout_seconds: float = 300,
        runner: Runner = subprocess.run,
        env: dict[str, str] | None = None,
    ):
        self._command = command
        self._model = model
        self._timeout = timeout_seconds
        self._runner = runner
        self._env = env

    def generate(
        self, prompt: str, *, system_prompt: str | None = None, input_text: str | None = None
    ) -> AIResult:
        if shutil.which(self._command) is None and self._runner is subprocess.run:
            raise AIUnavailableError(f"{self._command} コマンドが見つかりません")

        args = [self._command, "-p", prompt, "--output-format", "json"]
        args += ["--tools", "", "--no-session-persistence"]
        if system_prompt:
            args += ["--system-prompt", system_prompt]
        if self._model:
            args += ["--model", self._model]

        env = {k: v for k, v in (self._env or os.environ).items() if k not in _STRIPPED_ENV}
        # リポジトリの CLAUDE.md を拾わないよう、専用の空ディレクトリで実行する
        with tempfile.TemporaryDirectory(prefix="deep-tracker-ai-") as cwd:
            try:
                proc = self._runner(
                    args,
                    input=input_text,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    cwd=cwd,
                    env=env,
                )
            except FileNotFoundError as e:
                raise AIUnavailableError(f"{self._command} コマンドが見つかりません") from e
            except subprocess.TimeoutExpired as e:
                raise AITimeoutError(f"{self._timeout}秒でタイムアウトしました") from e

        payload = _parse_payload(proc.stdout)
        if payload is not None and payload.get("is_error"):
            result = str(payload.get("result") or "")
            if payload.get("api_error_status") == 429:
                raise RateLimitError(
                    result or "利用制限に達しました", parse_reset_text(result) or result or None
                )
            raise AIError(result or f"claude がエラーを返しました (exit {proc.returncode})")
        if proc.returncode != 0 or payload is None:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise AIError(f"claude が異常終了しました (exit {proc.returncode}): {detail[:500]}")
        return AIResult(text=str(payload.get("result") or ""), usage=payload.get("usage") or {})


def _parse_payload(stdout: str) -> dict | None:
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None
