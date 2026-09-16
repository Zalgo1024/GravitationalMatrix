"""SQLite 数据库备份脚本（WAL 安全）。

用 sqlite3 的 backup API 在线快照（服务运行中也可执行，不锁库、不含 WAL 残留），
保留最近 N 份（默认 14，约两周每日备份），更旧的自动删除。

用法（在 backend/ 目录下，或任意位置用绝对路径）：
    python scripts/backup_db.py
    python scripts/backup_db.py --keep 30 --out "D:\\我的备份\\引力矩阵"

可配置环境变量：
    APP_DB_PATH  数据库路径（与后端一致，默认 backend/data/app.db）
    BACKUP_DIR   备份输出目录（默认 backend/backups，已加入 .gitignore）

Windows 计划任务建议（每日 03:00）：
    schtasks /create /tn "GravityMatrix-DBBackup" /tr "backend\.venv\Scripts\python.exe scripts\backup_db.py" /sc daily /st 03:00
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "app.db"
DEFAULT_OUT = PROJECT_ROOT / "backend" / "backups"


def backup(db_path: Path, out_dir: Path, keep: int) -> Path:
    if not db_path.exists():
        print(f"[backup] 数据库不存在：{db_path}", file=sys.stderr)
        raise SystemExit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = out_dir / f"app_{stamp}.db"

    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        # WAL 模式下在线备份的标准姿势：backup API 会复制一致性的页面快照
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")  # 备份副本不需要 WAL 文件
        dst.commit()
    finally:
        dst.close()
        src.close()

    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"[backup] 完成：{target}（{size_mb:.1f} MB）")

    # 保留最近 keep 份
    backups = sorted(out_dir.glob("app_*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        try:
            old.unlink()
            print(f"[backup] 清理旧备份：{old.name}")
        except OSError as exc:
            print(f"[backup] 清理失败（跳过）{old.name}: {exc}", file=sys.stderr)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="引力矩阵引擎 — SQLite 备份")
    parser.add_argument("--out", default=os.environ.get("BACKUP_DIR", str(DEFAULT_OUT)))
    parser.add_argument("--db", default=os.environ.get("APP_DB_PATH", str(DEFAULT_DB)))
    parser.add_argument("--keep", type=int, default=14, help="保留最近 N 份（默认 14）")
    args = parser.parse_args()

    backup(Path(args.db).resolve(), Path(args.out).resolve(), max(0, args.keep))


if __name__ == "__main__":
    main()
