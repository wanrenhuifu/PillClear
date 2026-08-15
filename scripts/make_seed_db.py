"""把本机 SQLite 库 Consolidate 成随镜像分发的种子库 seed/pillclear.db。

用法（先在本机完成入库，再跑本脚本）：
    python -m app.knowledge.ingest data/package_inserts   # 需 .env 里的 LLM key
    python scripts/make_seed_db.py

原理：`VACUUM INTO` 产出单文件库（甩掉 WAL/SHM 附属文件），云平台构建时
COPY 进镜像即开箱可用，免去在 PaaS 上跑一次性 ingest（见 Dockerfile）。
仅标准库，与 install_hooks.py / pre_commit_check.py 同款约定。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import default_data_dir

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = REPO_ROOT / "seed" / "pillclear.db"


def main() -> None:
    src = default_data_dir() / "pillclear.db"
    if not src.is_file():
        raise SystemExit(f"未找到本机数据库 {src}——请先运行入库：python -m app.knowledge.ingest data/package_inserts")

    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SEED_PATH.exists():
        SEED_PATH.unlink()

    con = sqlite3.connect(src)
    try:
        con.execute("VACUUM INTO ?", (str(SEED_PATH),))
        drugs = con.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
        chunks = con.execute("SELECT COUNT(*) FROM insert_chunks").fetchone()[0]
    finally:
        con.close()

    print(f"种子库已生成：{SEED_PATH}（drugs={drugs}，chunks={chunks}，{SEED_PATH.stat().st_size} 字节）")
    print("下一步：git add seed/pillclear.db && 提交，重新构建镜像即带上新数据。")


if __name__ == "__main__":
    main()
