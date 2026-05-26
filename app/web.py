"""FastAPI Web 服务：对外提供 `/` 报告页与 `/healthz`。"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

import foundry_monitor as fm
import storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="Foundry Retirement Monitor")

SOURCE_URL = os.environ.get(
    "SOURCE_URL",
    "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule",
)
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))


def _build_report(force_refresh: bool) -> str:
    today = date.today()
    target = today + timedelta(days=WINDOW_DAYS)
    stored = [] if force_refresh else storage.load_yesterday()

    if stored:
        records = [
            fm.RetirementRecord(**{k: v for k, v in r.items()
                                   if k in fm.RetirementRecord.__dataclass_fields__})
            for r in stored
        ]
        records = fm.sort_records(records)
    else:
        html = fm.fetch_html(SOURCE_URL)
        all_records = fm.parse_tables(html)
        records = fm.filter_window(all_records, today, target)
        fm.detect_conflicts(records)
        records = fm.sort_records(records)

    return fm.render_email_html(
        records=records,
        today=today,
        target=target,
        source_url=SOURCE_URL,
        change_summary_html="",
    )


@app.get("/", response_class=HTMLResponse)
def report(fresh: int = Query(0, description="1=强制重新抓取")):
    try:
        return HTMLResponse(_build_report(force_refresh=bool(fresh)),
                            headers={"Cache-Control": "public, max-age=300"})
    except Exception as e:  # noqa: BLE001
        logging.exception("report failed")
        return HTMLResponse(f"<h1>报告生成失败</h1><pre>{e}</pre>", status_code=500)


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"
