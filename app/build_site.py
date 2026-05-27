"""生成 GitHub Pages 静态站点。

读取 `data/history.json` 中保存的最新快照，调用现有的 `render_email_html`
把内容渲染为 `site/index.html`。GitHub Actions 在 daily_job 跑完后执行本脚本，
随后把 `site/` 目录发布到 GitHub Pages。
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import foundry_monitor as fm
import storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SOURCE_URL = os.environ.get(
    "SOURCE_URL",
    "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule",
)
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))
OUT_DIR = Path(os.environ.get("SITE_OUT", "site"))


def main() -> int:
    snapshot_path = Path(os.environ.get("HISTORY_PATH", "data/history.json"))
    today = date.today()
    target = today + timedelta(days=WINDOW_DAYS)

    stored = storage.load_yesterday()
    snapshot_date_str = today.isoformat()
    if snapshot_path.exists():
        import json
        try:
            snapshot_date_str = json.loads(
                snapshot_path.read_text(encoding="utf-8")
            ).get("date", snapshot_date_str)
        except Exception:  # noqa: BLE001
            pass

    if not stored:
        logging.warning("快照为空，渲染空白页")
        records: list[fm.RetirementRecord] = []
    else:
        records = [
            fm.RetirementRecord(**{k: v for k, v in r.items()
                                   if k in fm.RetirementRecord.__dataclass_fields__})
            for r in stored
        ]
        records = fm.sort_records(records)

    html = fm.render_email_html(
        records=records,
        today=today,
        target=target,
        source_url=SOURCE_URL,
        change_summary_html=(
            f"<p style='color:#94a3b8;font-size:13px;margin:8px 0 0;'>"
            f"快照日期：{snapshot_date_str} · 由 GitHub Actions 每日 08:30 (CST) 自动更新"
            f"</p>"
        ),
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "index.html"
    out_file.write_text(html, encoding="utf-8")
    logging.info("已写入 %s (%d 条记录)", out_file, len(records))

    # GitHub Pages: prevent Jekyll processing
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
