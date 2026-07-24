"""数据同步命令行（在 backend/ 目录下运行）：

    python -m app.data.cli backfill --start 2010-01-01          # 首次建库（可加 --tables daily,adj_factor）
    python -m app.data.cli sync                                 # 每日增量（调度器每日 17:00 也走这里）
    python -m app.data.cli status                               # 查看各表覆盖范围
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from app.data.store import DuckDBStore
from app.data.sync import TABLE_SPECS, DataSyncer
from app.data.tushare_client import TushareClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _progress(name: str, i: int, total: int) -> None:
    if i % 100 == 0 or i == total:
        print(f"\r{name}: {i}/{total} 天", end="", flush=True)
        if i == total:
            print()


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.data.cli", description="行情数据同步")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_backfill = sub.add_parser("backfill", help="首次全量回填")
    p_backfill.add_argument("--start", type=_parse_date, default=None, help="起始日期，默认 2010-01-01")
    p_backfill.add_argument("--end", type=_parse_date, default=None, help="结束日期，默认今天")
    p_backfill.add_argument("--tables", type=str, default=None,
                            help=f"逗号分隔，可选：{','.join(TABLE_SPECS)}")

    p_sync = sub.add_parser("sync", help="每日增量同步")
    p_sync.add_argument("--tables", type=str, default=None)

    sub.add_parser("status", help="各表行数与日期范围")

    args = parser.parse_args()

    try:
        client = TushareClient()
    except RuntimeError as exc:
        print(f"错误：{exc}")
        return 2

    store = DuckDBStore()
    syncer = DataSyncer(client, store)

    if args.cmd == "backfill":
        tables = args.tables.split(",") if args.tables else None
        kwargs = {"end": args.end, "tables": tables, "progress": _progress}
        if args.start:
            kwargs["start"] = args.start
        results = syncer.backfill(**kwargs)
    elif args.cmd == "sync":
        tables = args.tables.split(",") if args.tables else None
        results = syncer.sync_incremental(tables)
    else:
        print(syncer.status().to_string(index=False))
        return 0

    print("\n同步结果：")
    for name, rows in results.items():
        flag = "（失败）" if rows == -1 else ""
        print(f"  {name:<14} {rows:>8} 行 {flag}")
    return 1 if any(v == -1 for v in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
