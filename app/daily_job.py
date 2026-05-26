"""CronJob 入口：抓取、对比、发邮件、保存当日快照。"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

import foundry_monitor as fm
import storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SOURCE_URL = os.environ.get(
    "SOURCE_URL",
    "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule",
)
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))


def _send_email(subject: str, html_body: str) -> None:
    webhook_url = os.environ.get("MAILER_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("MAILER_WEBHOOK_URL 未配置")

    payload = json.dumps({"subject": subject, "html": html_body}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        logging.info("邮件 webhook 已提交: status=%s", resp.status)


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

    _send_email(subject, html_body)
    logging.info("=== 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
