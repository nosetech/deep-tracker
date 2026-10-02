import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from deep_tracker.config.models import Settings

CONFIG_ENV = "DEEP_TRACKER_CONFIG"

# このファイルは <展開先>/backend/deep_tracker/config/loader.py にある
DEPLOY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = DEPLOY_ROOT / "config" / "config.yaml"


class ConfigError(Exception):
    """設定ファイルの読み込み・検証に失敗した。"""


def resolve_config_path() -> tuple[Path, bool]:
    """設定ファイルのパスと、環境変数で明示指定されたかどうかを返す。"""
    env = os.environ.get(CONFIG_ENV)
    if env:
        return Path(env).expanduser(), True
    return DEFAULT_CONFIG_PATH, False


def _format_errors(path: Path, err: ValidationError) -> str:
    lines = [f"設定ファイルが不正です: {path}"]
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(root)"
        lines.append(f"  - {loc}: {e['msg']}")
    return "\n".join(lines)


def load_settings(path: Path | None = None) -> Settings:
    """設定を読み込んで検証する。

    path 未指定時は環境変数 DEEP_TRACKER_CONFIG、なければ <展開先>/config/config.yaml を使う。
    既定位置のファイルが無い場合は既定値で動作する。明示指定したファイルが無い場合はエラー。
    """
    explicit = path is not None
    if path is None:
        path, explicit = resolve_config_path()

    if not path.is_file():
        if explicit:
            raise ConfigError(f"設定ファイルが見つかりません: {path}")
        data: object = {}
    else:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            raise ConfigError(f"設定ファイルを読み込めません: {path}\n  {e}") from e
        if not isinstance(data, dict):
            raise ConfigError(f"設定ファイルのトップレベルはマッピングにしてください: {path}")

    try:
        settings = Settings.model_validate(data)
    except ValidationError as e:
        raise ConfigError(_format_errors(path, e)) from e

    db_path = Path(settings.db.path).expanduser()
    if not db_path.is_absolute():
        settings.db.path = str(DEPLOY_ROOT / db_path)
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 設定は起動時に1度だけ読む（ホットリロードはしない。変更は再起動で反映）
    return load_settings()
