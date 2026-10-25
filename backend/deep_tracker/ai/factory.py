from deep_tracker.ai.base import AIProvider
from deep_tracker.ai.claude_code import ClaudeCodeCLIProvider
from deep_tracker.config.models import AIProviderName, AISettings


def create_provider(settings: AISettings) -> AIProvider:
    if settings.provider == AIProviderName.CLAUDE_CODE:
        return ClaudeCodeCLIProvider(
            command=settings.command,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
        )
    raise ValueError(f"未対応のAIプロバイダ: {settings.provider}")
