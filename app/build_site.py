"""生成 GitHub Pages 静态站点（实时抓取版）。

每次运行都重新抓取 MS Learn 退役时间表，渲染当前最新报告到 `site/index.html`。
不读 / 不写 history 快照（diff 用 daily_job 跑）。
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import foundry_monitor as fm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SOURCE_URL = os.environ.get(
    "SOURCE_URL",
    "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule",
)
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))
OUT_DIR = Path(os.environ.get("SITE_OUT", "site"))


def _now_cst_str() -> str:
    cst = timezone(timedelta(hours=8))
    return datetime.now(cst).strftime("%Y-%m-%d %H:%M:%S CST")


def main() -> int:
    today = date.today()
    target = today + timedelta(days=WINDOW_DAYS)

    try:
        html_raw = fm.fetch_html(SOURCE_URL)
        all_records = fm.parse_tables(html_raw)
        records = fm.filter_window(all_records, today, target)
        fm.detect_conflicts(records)
        records = fm.sort_records(records)
        fetch_note = f"实时抓取于 {_now_cst_str()}"
        logging.info("fetched %d records (window)", len(records))
    except Exception as e:  # noqa: BLE001
        logging.exception("fetch failed")
        records = []
        fetch_note = f"⚠️ 抓取失败 ({_now_cst_str()}): {e}"

    html = fm.render_email_html(
        records=records,
        today=today,
        target=target,
        source_url=SOURCE_URL,
        change_summary_html=(
            f"<p style='color:#94a3b8;font-size:13px;margin:8px 0 0;'>"
            f"{fetch_note} · 每 15 分钟自动刷新 · "
            f"每日 08:30 CST 由 GitHub Actions 发邮件"
            f"</p>"
        ),
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    logging.info("wrote %s/index.html", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
