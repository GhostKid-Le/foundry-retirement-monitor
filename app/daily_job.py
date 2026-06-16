"""CronJob 入口：抓取、对比、发邮件、保存当日快照。"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
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
    """把渲染好的邮件写成 JSON快照，随快照一起 commit 回仓库作审计留痕。

    发信本身由 GitHub Actions 调 Resend API 直接完成（见 _send_email），
    本文件仅供“今天发了什么”的可追溯记录，不再被外部拉取。
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
    logging.info("已写出邮件快照: %s (changed=%s)", out, changed)


def _send_email(subject: str, html_body: str) -> None:
    """通过 Resend API 直接发信。

    需环境变量 RESEND_API_KEY 与 MAIL_TO（多收件人逗号/分号分隔）；
    MAIL_FROM 可选，默认用 Resend 测试发件地址。缺密钥时（如本地）
    跳过发送、仅保留快照，便于安全调试。
    """
    api_key = os.environ.get("RESEND_API_KEY")
    mail_to = os.environ.get("MAIL_TO")
    if not (api_key and mail_to):
        logging.warning("未配置 RESEND_API_KEY / MAIL_TO，跳过发信（仅写快照）")
        return

    # 用 `or` 而非 get 默认值：workflow 注入空串 secret 时也能回退到默认发件人
    mail_from = os.environ.get("MAIL_FROM") or "Foundry Monitor <onboarding@resend.dev>"
    recipients = [a.strip() for a in mail_to.replace(";", ",").split(",") if a.strip()]
    payload = json.dumps(
        {"from": mail_from, "to": recipients, "subject": subject, "html": html_body}
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # 默认 Python-urllib UA 会被 Resend 前置的 Cloudflare 拦截(error 1010)
            "User-Agent": "foundry-retirement-monitor/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            logging.info("Resend 已接受邮件: status=%s", resp.status)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        logging.error("Resend 拒绝(%s): %s", e.code, body)
        raise


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
    _send_email(subject, html_body)
    logging.info("=== 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
