"""
Azure Functions 入口
- Timer trigger `daily_check`：每日 08:30 (WEBSITE_TIME_ZONE) 拉取退役日程并发邮件。
- HTTP trigger `report`：匿名访问，返回响应式 HTML 报告，便于分享给他人。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, date

import urllib.request
import urllib.error

import azure.functions as func
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient

import foundry_monitor as fm

app = func.FunctionApp()

# 默认 cron: 每日 08:30（受 WEBSITE_TIME_ZONE 影响）
SCHEDULE = os.environ.get("SCHEDULE_CRON", "0 30 8 * * *")


def _credential():
    client_id = os.environ.get("AZURE_CLIENT_ID")
    if client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return DefaultAzureCredential()


def _blob_client() -> BlobServiceClient | None:
    account = os.environ.get("STORAGE_ACCOUNT_NAME")
    if not account:
        logging.warning("STORAGE_ACCOUNT_NAME 未配置，跳过 Blob 持久化")
        return None
    return BlobServiceClient(
        account_url=f"https://{account}.blob.core.windows.net",
        credential=_credential(),
    )


def _load_yesterday() -> list[dict]:
    bsc = _blob_client()
    if not bsc:
        return []
    container = os.environ.get("HISTORY_CONTAINER", "history")
    blob_name = os.environ.get("HISTORY_BLOB", "foundry_retirement_history.json")
    try:
        blob = bsc.get_blob_client(container=container, blob=blob_name)
        if not blob.exists():
            return []
        data = json.loads(blob.download_blob().readall().decode("utf-8"))
        return data.get("records", [])
    except Exception as e:  # noqa: BLE001
        logging.warning("读取历史 blob 失败: %s", e)
        return []


def _save_today(records: list) -> None:
    bsc = _blob_client()
    if not bsc:
        return
    container = os.environ.get("HISTORY_CONTAINER", "history")
    blob_name = os.environ.get("HISTORY_BLOB", "foundry_retirement_history.json")
    payload = {
        "date": date.today().isoformat(),
        "records": fm.to_dicts(records),
    }
    try:
        bsc.get_blob_client(container=container, blob=blob_name).upload_blob(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            overwrite=True,
        )
    except Exception as e:  # noqa: BLE001
        logging.error("写入历史 blob 失败: %s", e)


def _send_email(subject: str, html_body: str) -> None:
    """通过 Power Automate webhook 发送邮件（发件人 = wang.le@microsoft.com）。
    收件人列表在 Power Automate Flow 的 "Send an email (V2)" 步骤里维护。
    """
    webhook_url = os.environ.get("MAILER_WEBHOOK_URL")
    if not webhook_url:
        logging.error("MAILER_WEBHOOK_URL 未配置，无法发送邮件")
        return

    payload = json.dumps({"subject": subject, "html": html_body}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            logging.info("邮件 webhook 已提交: status=%s", resp.status)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logging.error("邮件 webhook 失败 HTTP %s: %s", e.code, body[:500])
        raise
    except urllib.error.URLError as e:
        logging.error("邮件 webhook 连接失败: %s", e)
        raise


@app.function_name(name="daily_check")
@app.timer_trigger(schedule=SCHEDULE, arg_name="timer", run_on_startup=False, use_monitor=True)
def daily_check(timer: func.TimerRequest) -> None:
    logging.info("=== Foundry 退役监控开始 ===")
    today = date.today()
    window_days = int(os.environ.get("WINDOW_DAYS", "30"))
    target = today + timedelta(days=window_days)
    source_url = os.environ.get(
        "SOURCE_URL",
        "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule",
    )

    # 1) 抓取 + 解析
    html = fm.fetch_html(source_url)
    all_records = fm.parse_tables(html)
    logging.info("解析到 %d 条原始记录", len(all_records))

    # 2) 窗口过滤 + 冲突 + 历史 diff + 排序
    window_records = fm.filter_window(all_records, today, target)
    fm.detect_conflicts(window_records)

    yesterday = _load_yesterday()
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

    # 3) 总是更新历史（保持滚动）
    _save_today(window_records)

    # 4) 渲染邮件（每天都发；主题在「有变化」时高亮）
    summary_html = fm.render_change_summary(changes) if changes["changed"] else ""
    html_body = fm.render_email_html(
        records=window_records,
        today=today,
        target=target,
        source_url=source_url,
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


# ----------------------------- HTTP: 公开报告页面 -----------------------------

def _build_report_html(force_refresh: bool = False) -> tuple[str, dict]:
    """构造可分享的 HTML 报告。优先使用已存的 blob 数据；force_refresh=true 时重新抓取。"""
    today = date.today()
    window_days = int(os.environ.get("WINDOW_DAYS", "30"))
    target = today + timedelta(days=window_days)
    source_url = os.environ.get(
        "SOURCE_URL",
        "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule",
    )

    stored = [] if force_refresh else _load_yesterday()
    if stored and not force_refresh:
        # 用最近一次定时任务的快照渲染（快速、稳定）
        records = [fm.RetirementRecord(**{k: v for k, v in r.items()
                                          if k in fm.RetirementRecord.__dataclass_fields__})
                   for r in stored]
        records = fm.sort_records(records)
        meta = {"source": "snapshot", "count": len(records)}
    else:
        html = fm.fetch_html(source_url)
        all_records = fm.parse_tables(html)
        records = fm.filter_window(all_records, today, target)
        fm.detect_conflicts(records)
        records = fm.sort_records(records)
        meta = {"source": "live", "count": len(records)}

    body = fm.render_email_html(
        records=records,
        today=today,
        target=target,
        source_url=source_url,
        change_summary_html="",
    )
    return body, meta


@app.function_name(name="report")
@app.route(route="report", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def report(req: func.HttpRequest) -> func.HttpResponse:
    """公开访问的报告页面，可直接分享 URL。
    用法：
      GET /api/report           → 用最近一次定时任务快照渲染
      GET /api/report?fresh=1   → 重新抓取页面（约 2~5s）
    """
    fresh = req.params.get("fresh", "").lower() in ("1", "true", "yes")
    try:
        html_body, meta = _build_report_html(force_refresh=fresh)
        logging.info("report served: %s", meta)
        return func.HttpResponse(
            html_body,
            status_code=200,
            mimetype="text/html",
            charset="utf-8",
            headers={"Cache-Control": "public, max-age=300"},  # 浏览器缓存 5 分钟
        )
    except Exception as e:  # noqa: BLE001
        logging.exception("report failed")
        return func.HttpResponse(
            f"<h1>报告生成失败</h1><pre>{e}</pre>",
            status_code=500,
            mimetype="text/html",
        )
