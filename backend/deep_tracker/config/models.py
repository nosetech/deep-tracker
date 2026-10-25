from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class _Section(BaseModel):
    # 綴り間違いのキーを黙って無視しないよう、未知のキーはエラーにする
    model_config = ConfigDict(extra="forbid")


class SummaryInterval(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class BackendSettings(_Section):
    # バックエンドは常に 127.0.0.1 に bind する（LAN公開はフロントのみ。architecture.md 2-5）
    port: int = Field(8700, ge=1, le=65535)


class FrontendSettings(_Section):
    # LAN公開する場合は 0.0.0.0 にする
    host: str = "127.0.0.1"
    port: int = Field(3700, ge=1, le=65535)


class DbSettings(_Section):
    # 相対パスは展開先ディレクトリ基準で解決される
    path: str = "data/deep-tracker.db"


class RetentionSettings(_Section):
    days: int = Field(365, ge=1)


class SummarySettings(_Section):
    interval: SummaryInterval = SummaryInterval.WEEKLY


class SlackSettings(_Section):
    enabled: bool = False
    webhook_url: HttpUrl | None = None
    # サマリ生成の失敗も通知するか
    notify_on_failure: bool = True
    # 通知に含めるGUIリンクのベースURL。未指定なら frontend.host / port から組み立てる
    base_url: HttpUrl | None = None

    @model_validator(mode="after")
    def _require_webhook_url(self) -> "SlackSettings":
        if self.enabled and self.webhook_url is None:
            raise ValueError("slack.enabled が true の場合は slack.webhook_url が必要です")
        return self


class AIProviderName(StrEnum):
    CLAUDE_CODE = "claude_code"


class AISettings(_Section):
    provider: AIProviderName = AIProviderName.CLAUDE_CODE
    # Claude Code CLI の実行パス。launchd では PATH が限られるため、絶対パスの指定を推奨
    command: str = Field("claude", min_length=1)
    model: str | None = None  # 未指定ならCLIの既定
    timeout_seconds: float = Field(300, gt=0)
    # AIジョブの同時実行数。サブスクリプションの制限を踏まえ、既定は逐次（1）
    max_concurrent_jobs: int = Field(1, ge=1)


class FeedSettings(_Section):
    fetch_interval_minutes: int = Field(60, ge=1)


class Settings(_Section):
    instance: str = Field("default", pattern=r"^[A-Za-z0-9._-]+$")
    backend: BackendSettings = BackendSettings()
    frontend: FrontendSettings = FrontendSettings()
    db: DbSettings = DbSettings()
    retention: RetentionSettings = RetentionSettings()
    summary: SummarySettings = SummarySettings()
    slack: SlackSettings = SlackSettings()
    feed: FeedSettings = FeedSettings()
    ai: AISettings = AISettings()

    @property
    def lan_exposed(self) -> bool:
        return self.frontend.host == "0.0.0.0"  # noqa: S104
