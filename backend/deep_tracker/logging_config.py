"""ロギング設定: JST固定のフォーマット・日次（JST 0時）ローテーション。

backend / frontend / 定期バッチの全ログで共通。`TimedRotatingFileHandler` が世代管理
（保持日数を超えたファイルの削除）まで行うため、自前のファイル走査は持たない。
"""

import logging
import logging.handlers
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from deep_tracker.config.loader import LOG_DIR

JST = timezone(timedelta(hours=9))

# uvicorn は独自のハンドラを持つため、ルートへ流す（ハンドラは外す）
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class JstFormatter(logging.Formatter):
    """`%(asctime)s` をOSのタイムゾーンに依存させず、常にJSTで出力する。"""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=JST)
        if datefmt:
            return dt.strftime(datefmt)
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')},{int(record.msecs):03d}"


class JstMidnightRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """日次ローテーションの0時判定と世代ファイル名（`*.log.YYYY-MM-DD`）をJSTに固定する。

    標準の `when="midnight"` は OS のタイムゾーンで0時を判定するため、OSがJST以外だと
    ログ内の時刻（JstFormatter）とファイルの区切りがずれる。
    """

    def __init__(self, filename: Path | str, *, backup_count: int) -> None:
        super().__init__(filename, when="midnight", backupCount=backup_count, encoding="utf-8")

    def computeRollover(self, currentTime: int) -> int:
        now = datetime.fromtimestamp(currentTime, tz=JST)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int(next_midnight.timestamp())

    def rotation_filename(self, default_name: str) -> str:
        # doRollover() は rolloverAt を更新する前にこれを呼ぶ。rolloverAt の1秒前が「終わった日」
        ended_day = datetime.fromtimestamp(self.rolloverAt - 1, tz=JST)
        return f"{self.baseFilename}.{ended_day.strftime('%Y-%m-%d')}"

    def getFilesToDelete(self) -> list[str]:
        # 標準実装は既定の接尾辞（YYYY-MM-DD_HH-MM-SS 形式）の正規表現で探すため、
        # JST固定の世代ファイル名（YYYY-MM-DD）に合わせて自前で探す
        base = Path(self.baseFilename)
        pattern = f"{base.name}.????-??-??"
        files = sorted(
            p for p in base.parent.glob(pattern) if p.name[len(base.name) + 1 :].count("-") == 2
        )
        if len(files) <= self.backupCount:
            return []
        return [str(p) for p in files[: len(files) - self.backupCount]]


def configure_logging(
    filename: str,
    *,
    retention_days: int,
    log_dir: Path = LOG_DIR,
    console: bool = False,
    level: int = logging.INFO,
) -> None:
    """ルートロガーを、日次ローテーションのファイルハンドラ（と任意でコンソール）に設定する。

    console は端末から手動実行するときだけ使う（launchd 配下では出力が `*.launchd.log` に
    重複して溜まるため無効にする）。二重呼び出しでハンドラが積み上がらないよう、既存は閉じて外す。
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = JstFormatter("%(asctime)s [%(levelname)s] %(message)s")

    handlers: list[logging.Handler] = [
        JstMidnightRotatingFileHandler(log_dir / filename, backup_count=retention_days)
    ]
    if console:
        handlers.append(logging.StreamHandler(sys.stdout))

    root = logging.getLogger()
    root.setLevel(level)
    for existing in root.handlers[:]:
        root.removeHandler(existing)
        existing.close()
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)

    for name in _UVICORN_LOGGERS:
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
