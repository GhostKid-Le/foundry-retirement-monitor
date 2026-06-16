"""CronJob 入口：抓取、对比、发邮件、保存当日快照。"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import foundry_monitor as fm
import storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SOURCE_URL = os.environ.get(
    "SOURCE_URL",
    "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule",
)
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))


EMAIL_PAYLOAD_PATH = os.environ.get("EMAIL_PAYLOAD_PATH", "data/email.json")


def _write_email_payload(subject: str, html_body: str, changed: bool) -> None:
    """把渲染好的邮件写成 JSON，供 Power Automate 定时拉取后发送。

    不再主动 POST webhook：改由 Power Automate 的 Recurrence（定时）触发器
    HTTP GET 本文件的公开 raw URL，从根上消除“谁可以触发 webhook”的问题（合规）。
    """
    payload = {
        "subject": subject,
        "html": html_body,
        "changed": changed,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    out = Path(EMAIL_PAYLOAD_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logging.info("已写出邮件载荷: %s (changed=%s)", out, changed)


def main() -> int:
    logging.info("=== Foundry 退役监控开始 ===")
    today = date.today()
    target = today + timedelta(days=WINDOW_DAYS)

    html = fm.fetch_html(SOURCE_URL)
    all_records = fm.parse_tables(html)
    logging.info("解析到 %d 条原始记录", len(all_records))

    window_records = fm.filter_window(all_records, today, target)
    fm.detect_conflicts(window_records)

    yesterday = storage.load_yesterday()
    fm.diff_with_yesterday(window_records, yesterday)
    window_records = fm.sort_records(window_records)

    changes = fm.has_changes(window_records, yesterday)
    logging.info(
        "窗口 %d 条；新增 %d 变更 %d 移除 %d",
        len(window_records),
        len(changes["new"]),
        len(changes["modified"]),
        len(changes["removed"]),
    )

    storage.save_today(window_records)

    summary_html = fm.render_change_summary(changes) if changes["changed"] else ""
    html_body = fm.render_email_html(
        records=window_records,
        today=today,
        target=target,
        source_url=SOURCE_URL,
        change_summary_html=summary_html,
    )

    is_first_run = not yesterday
    if is_first_run:
        subject = (
            f"[Foundry 未来 30 天退役监控] {today.isoformat()} · 首次运行 baseline "
            f"({len(window_records)} 条)"
        )
    elif changes["changed"]:
        subject = (
            f"🔔 [Foundry 未来 30 天退役监控] {today.isoformat()} · 有变更："
            f"新增 {len(changes['new'])} / 变更 {len(changes['modified'])} / 移除 {len(changes['removed'])}"
        )
    else:
        subject = (
            f"[Foundry 未来 30 天退役监控] {today.isoformat()} · 无变化 "
            f"({len(window_records)} 条)"
        )

    _write_email_payload(subject, html_body, changes["changed"])
    logging.info("=== 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
