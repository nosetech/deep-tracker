from fastapi import APIRouter
from pydantic import BaseModel

from deep_tracker.config import get_settings

router = APIRouter()


class PublicConfig(BaseModel):
    """frontend が参照してよい設定値。Webhook URL など秘匿値は含めない。"""

    instance: str
    retention_days: int
    summary_interval: str
    slack_enabled: bool
    feed_fetch_interval_minutes: int


@router.get("/config", response_model=PublicConfig)
def get_config() -> PublicConfig:
    s = get_settings()
    return PublicConfig(
        instance=s.instance,
        retention_days=s.retention.days,
        summary_interval=s.summary.interval.value,
        slack_enabled=s.slack.enabled,
        feed_fetch_interval_minutes=s.feed.fetch_interval_minutes,
    )
