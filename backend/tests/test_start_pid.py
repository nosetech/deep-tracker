"""scripts/lib.sh の start_backend が、PID ファイルにサーバー自身の PID を書くことのテスト。

偽の venv python（exec sleep）を置き、起動された PID のコマンドが bash ではないことを確認する。
"""

import os
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib.sh"


def _comm(pid: int) -> str:
    out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True)
    return os.path.basename(out.stdout.strip())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_start_backend_writes_server_pid(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    lib = root / "scripts" / "lib.sh"
    lib.write_text(LIB.read_text())
    fake_py = root / "backend" / ".venv" / "bin" / "python"
    fake_py.parent.mkdir(parents=True)
    fake_py.write_text("#!/bin/sh\nexec sleep 60\n")
    fake_py.chmod(0o755)
    log_dir = tmp_path / "log"

    common = f"""
set -euo pipefail
source "{lib}"
INSTANCE=test
LOG_DIR="{log_dir}"
PID_DIR="{log_dir}"
LOG_RETENTION_DAYS=1
service_registered() {{ return 1; }}
"""
    env = dict(os.environ)
    subprocess.run(["bash", "-c", common + "start_backend"], check=True, env=env)

    pid_file = log_dir / "deep-tracker.test.backend.pid"
    pid = int(pid_file.read_text())
    try:
        # bash（起動用サブシェル）ではなく、起動対象（exec された sleep）の PID であること
        for _ in range(50):
            if _comm(pid) == "sleep":
                break
            time.sleep(0.1)
        assert _comm(pid) == "sleep"

        subprocess.run(["bash", "-c", common + "stop_service backend"], check=True, env=env)
        for _ in range(50):
            if not _alive(pid):
                break
            time.sleep(0.1)
        assert not _alive(pid)
        assert not pid_file.exists()
    finally:
        if _alive(pid):
            os.kill(pid, 9)
