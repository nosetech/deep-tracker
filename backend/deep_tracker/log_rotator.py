"""標準入力を読み、日次ローテーション付きでファイルへ書き出す小さなローテータ。

起動スクリプト（scripts/start.sh・launchd の plist）は、本体（backend / frontend）の
stdout/stderr をこのプロセスへパイプする。シェルの `>>` だと、ローテーションで rename された後も
旧ファイルへ書き続けるため、書き込み側（このプロセス）が自分でファイルを開き直す方式にしている。

使い方: `python -m deep_tracker.log_rotator --path <file> [--retention-days <n>]`
"""

import argparse
import logging
import sys
from collections.abc import Iterable
from pathlib import Path

from deep_tracker.config import get_settings
from deep_tracker.config.models import DEFAULT_LOG_RETENTION_DAYS
from deep_tracker.logging_config import JstMidnightRotatingFileHandler


def rotate_stream(lines: Iterable[str], path: Path, retention_days: int) -> None:
    """`lines` をEOFまで1行ずつ、加工せずそのまま書き出す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = JstMidnightRotatingFileHandler(path, backup_count=retention_days)
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        for line in lines:
            try:
                record = logging.LogRecord("", logging.INFO, "", 0, line.rstrip("\r\n"), None, None)
                handler.handle(record)
            except Exception:
                # 書き込み失敗でローテータが落ちると、本体が SIGPIPE を受けて巻き込まれる
                continue
    finally:
        handler.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--retention-days", type=int, default=None)
    args = parser.parse_args(argv)

    retention_days = args.retention_days
    if retention_days is None:
        try:
            retention_days = get_settings().logging.retention_days
        except Exception as e:
            # 設定が読めなくてもローテータは落とさない。設定ミスは本体側で起動時エラーになる
            print(f"log_rotator: 保持日数を読めないため既定値を使います: {e}", file=sys.stderr)
            retention_days = DEFAULT_LOG_RETENTION_DAYS
    # 不正なUTF-8バイトでも落とさない
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    rotate_stream(sys.stdin, args.path, max(1, retention_days))


if __name__ == "__main__":
    main()
