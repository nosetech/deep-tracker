from deep_tracker.ai.base import AIError, AIProvider, AIResult
from deep_tracker.ai.claude_code import ClaudeCodeCLIProvider
from deep_tracker.config.dev import is_dev_mode
from deep_tracker.config.models import AIProviderName, AISettings


class DevModeProvider(AIProvider):
    """動作確認用インスタンス向け。サブスクリプションを消費しないよう、常に拒否する。"""

    def generate(
        self, prompt: str, *, system_prompt: str | None = None, input_text: str | None = None
    ) -> AIResult:
        raise AIError("動作確認用インスタンスではAI呼び出しを実行しません")


def create_provider(settings: AISettings) -> AIProvider:
    if is_dev_mode():
        return DevModeProvider()
    if settings.provider == AIProviderName.CLAUDE_CODE:
        return ClaudeCodeCLIProvider(
            command=settings.command,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
        )
    raise ValueError(f"未対応のAIプロバイダ: {settings.provider}")
