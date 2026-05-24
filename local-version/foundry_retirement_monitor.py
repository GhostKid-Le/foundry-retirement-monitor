"""
Azure AI Foundry 模型退役监控器
- 抓取 Microsoft Learn 官方退役计划页面
- 提取未来 30 天内即将退役的模型
- 冲突检测 + 与昨日数据 diff
- 输出美观 HTML 报告
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

# ----------------------------- 配置 -----------------------------

SOURCE_URL = (
    "https://learn.microsoft.com/en-us/azure/foundry/openai/"
    "concepts/model-retirement-schedule"
)
# 备用地址（官网近期 URL 调整过）
FALLBACK_URLS = [
    "https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/model-retirement-schedule",
    "https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/model-retirements",
]

BASE_DIR = Path(__file__).parent
HISTORY_FILE = BASE_DIR / "foundry_retirement_history.json"
OUTPUT_HTML = BASE_DIR / "foundry_retirement_report.html"

WINDOW_DAYS = 30


# ----------------------------- 数据模型 -----------------------------

@dataclass
class RetirementRecord:
    model: str
    version: str
    lifecycle: str
    retirement_date: str  # ISO 格式 yyyy-mm-dd（无法解析则保留原文）
    replacement: str
    raw_retirement_date: str = ""
    conflict: str = "No"
    conflict_note: str = ""
    is_new: bool = False

    def key(self) -> tuple[str, str]:
        return (self.model.strip().lower(), self.version.strip().lower())


# ----------------------------- 抓取 -----------------------------

def fetch_html() -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    urls = [SOURCE_URL] + FALLBACK_URLS
    last_err: Exception | None = None
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            # 强制 UTF-8 解码，避免 em-dash 等字符出现 â�� 乱码
            resp.encoding = "utf-8"
            if resp.status_code == 200 and "retire" in resp.text.lower():
                print(f"[OK] 已抓取: {url}")
                return resp.text
            last_err = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[WARN] 抓取失败 {url}: {e}")
    raise RuntimeError(f"全部数据源抓取失败: {last_err}")


# ----------------------------- 日期解析 -----------------------------

DATE_PATTERNS = [
    "%B %d, %Y",   # November 30, 2025
    "%b %d, %Y",   # Nov 30, 2025
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d %B %Y",
    "%d %b %Y",
]


def parse_date(text: str) -> date | None:
    if not text:
        return None
    s = re.sub(r"\s+", " ", text).strip().rstrip(".")
    # 去除"No earlier than"/"at the earliest" 等修饰
    s = re.sub(
        r"(?i)(no earlier than|at the earliest|on or after|after|by|before)\s+",
        "",
        s,
    )
    # 抓取首个像日期的字符串
    m = re.search(
        r"([A-Za-z]+\s+\d{1,2},\s*\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        s,
    )
    if m:
        s = m.group(1)
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ----------------------------- 表格解析 -----------------------------

EXPECTED_COLS = {"model", "version", "lifecycle", "retirement", "replacement", "legacy"}


def _normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", h).strip().lower()


def parse_tables(html: str) -> list[RetirementRecord]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[RetirementRecord] = []

    for table in soup.find_all("table"):
        headers_row = table.find("tr")
        if not headers_row:
            continue
        headers = [
            _normalize_header(th.get_text(" ", strip=True))
            for th in headers_row.find_all(["th", "td"])
        ]
        # 仅认列里同时包含 model & retirement 的表格
        joined = " ".join(headers)
        if not ("model" in joined and "retirement" in joined):
            continue

        # 建立列索引映射
        def find_col(*keywords: str) -> int:
            for i, h in enumerate(headers):
                if all(k in h for k in keywords):
                    return i
            return -1

        idx_model = find_col("model")
        idx_version = find_col("version")
        if idx_version == -1:
            idx_version = find_col("legacy")  # 有的表是 "Legacy models"
        idx_lifecycle = find_col("lifecycle")
        if idx_lifecycle == -1:
            idx_lifecycle = find_col("status")
        idx_retire = find_col("retirement")
        idx_replace = find_col("replacement")
        if idx_replace == -1:
            idx_replace = find_col("suggested")

        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            vals = [c.get_text(" ", strip=True) for c in cells]

            def get(i: int) -> str:
                return vals[i] if 0 <= i < len(vals) else ""

            model = get(idx_model)
            if not model:
                continue
            rec = RetirementRecord(
                model=model,
                version=get(idx_version),
                lifecycle=get(idx_lifecycle) or "GA",
                retirement_date="",
                replacement=get(idx_replace),
                raw_retirement_date=get(idx_retire),
            )
            d = parse_date(rec.raw_retirement_date)
            rec.retirement_date = d.isoformat() if d else rec.raw_retirement_date
            records.append(rec)

    return records


# ----------------------------- 过滤 + 冲突 + Diff -----------------------------

def filter_window(records: list[RetirementRecord], today: date, target: date) -> list[RetirementRecord]:
    out = []
    for r in records:
        d = parse_date(r.raw_retirement_date)
        if d is None:
            continue
        if today <= d <= target:
            out.append(r)
    return out


def detect_conflicts(records: list[RetirementRecord]) -> None:
    """同一 (Model, Version) 出现多条 → 标记 Conflict=Yes 并附备注。"""
    groups: dict[tuple[str, str], list[RetirementRecord]] = {}
    for r in records:
        groups.setdefault(r.key(), []).append(r)

    for key, group in groups.items():
        if len(group) <= 1:
            continue
        dates = {r.retirement_date for r in group}
        replaces = {r.replacement for r in group}
        lifecycles = {r.lifecycle for r in group}
        if len(dates) > 1 or len(replaces) > 1 or len(lifecycles) > 1:
            for r in group:
                others = [o for o in group if o is not r]
                notes = []
                for o in others:
                    notes.append(
                        f"其他记录: 日期={o.retirement_date or '-'}, "
                        f"Lifecycle={o.lifecycle or '-'}, "
                        f"Replacement={o.replacement or '-'}"
                    )
                r.conflict = "Yes"
                r.conflict_note = " | ".join(notes)


def sort_records(records: list[RetirementRecord]) -> list[RetirementRecord]:
    def sort_key(r: RetirementRecord):
        has_repl = 0 if r.replacement.strip() else 1  # 有 Replacement 优先
        d = parse_date(r.raw_retirement_date) or date.max
        # 较晚优先 → 用负序：使用 (date.max - d).days 让晚的更小
        date_rank = -(d.toordinal())
        lifecycle_rank = 0 if "deprecat" in r.lifecycle.lower() else 1
        return (has_repl, date_rank, lifecycle_rank, r.model.lower(), r.version.lower())
    return sorted(records, key=sort_key)


def diff_with_yesterday(
    today_records: list[RetirementRecord],
    yesterday: list[dict[str, Any]],
) -> list[RetirementRecord]:
    y_keys = {
        (str(r.get("model", "")).strip().lower(), str(r.get("version", "")).strip().lower())
        for r in yesterday
    }
    for r in today_records:
        if r.key() not in y_keys:
            r.is_new = True
    return today_records


# ----------------------------- 历史 -----------------------------

def load_yesterday() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data.get("records", [])
    except Exception:  # noqa: BLE001
        return []


def save_today(records: list[RetirementRecord]) -> None:
    HISTORY_FILE.write_text(
        json.dumps(
            {
                "date": date.today().isoformat(),
                "records": [asdict(r) for r in records],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ----------------------------- HTML 渲染 -----------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<title>Azure AI Foundry 模型退役监控报告</title>
<style>
  :root {
    --bg: #0f172a;
    --card: #1e293b;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --warn: #fbbf24;
    --danger: #f87171;
    --ok: #34d399;
    --border: #334155;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: var(--text);
    min-height: 100vh;
    padding: 32px 16px;
  }
  .container { max-width: 1200px; margin: 0 auto; }
  header {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px 28px;
    margin-bottom: 24px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.3);
  }
  h1 {
    margin: 0 0 8px;
    font-size: 24px;
    background: linear-gradient(90deg, #38bdf8, #a78bfa);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
  }
  .meta { color: var(--muted); font-size: 14px; }
  .meta span { margin-right: 18px; }
  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
  }
  .badge.new { background: #1e3a8a; color: #93c5fd; }
  .badge.conflict { background: #7f1d1d; color: #fecaca; }
  .badge.ok { background: #064e3b; color: #6ee7b7; }
  .badge.deprecated { background: #78350f; color: #fcd34d; }
  .badge.ga { background: #1e293b; color: #cbd5e1; border: 1px solid var(--border); }

  .summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px;
    margin-top: 18px;
  }
  .stat {
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
  }
  .stat .n { font-size: 26px; font-weight: 700; color: var(--accent); }
  .stat .l { font-size: 12px; color: var(--muted); margin-top: 2px; }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px;
    margin-bottom: 24px;
    overflow-x: auto;
  }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td {
    padding: 10px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  th {
    color: var(--muted);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.5px;
    position: sticky;
    top: 0;
    background: var(--card);
  }
  tr:hover td { background: rgba(56,189,248,0.05); }
  tr.is-new td { font-weight: 700; background: rgba(59,130,246,0.08); }
  tr.is-conflict td { background: rgba(248,113,113,0.06); }
  tr.is-new.is-conflict td { background: rgba(168,85,247,0.10); }
  td.nowrap, th.nowrap { white-space: nowrap; }
  .note {
    font-size: 11px;
    color: var(--warn);
    margin-top: 4px;
    font-style: italic;
    font-weight: normal;
  }
  .footer {
    margin-top: 18px;
    padding: 14px 18px;
    border-radius: 12px;
    background: rgba(251,191,36,0.08);
    border-left: 3px solid var(--warn);
    color: #fde68a;
    font-size: 13px;
    line-height: 1.7;
  }
  .new-note {
    margin-top: 12px;
    padding: 10px 14px;
    background: rgba(59,130,246,0.12);
    border-left: 3px solid var(--accent);
    border-radius: 6px;
    font-size: 13px;
    color: #bfdbfe;
  }
  .src { font-size: 12px; color: var(--muted); margin-top: 8px; }
  .src a { color: var(--accent); text-decoration: none; }
  .src a:hover { text-decoration: underline; }
  .empty {
    text-align: center;
    padding: 40px;
    color: var(--muted);
  }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>🛰️ Azure AI Foundry · 模型退役监控报告</h1>
    <div class="meta">
      <span>📅 当前日期: <b>{current_date}</b></span>
      <span>🎯 截止日期: <b>{target_date}</b></span>
      <span>🕒 生成时间: {generated_at}</span>
    </div>
    <div class="summary-grid">
      <div class="stat"><div class="n">{total}</div><div class="l">窗口内退役条数</div></div>
      <div class="stat"><div class="n">{new_count}</div><div class="l">今日新增</div></div>
      <div class="stat"><div class="n">{conflict_count}</div><div class="l">冲突记录</div></div>
      <div class="stat"><div class="n">{deprecated_count}</div><div class="l">Deprecated</div></div>
    </div>
    <div class="src">数据源: <a href="{source}" target="_blank">{source}</a></div>
  </header>

  <div class="card">
    {table_html}
    {new_note_html}
  </div>

  <div class="footer">
    ⚠️ <b>数据一致性声明：</b>
    如果存在 Model 信息与历史认知不一致、Retirement date 异常变化、或同页面字段不一致的情况，
    该数据可能存在版本差异（如 Microsoft Learn 页面缓存或延迟更新），
    建议结合 Azure Portal 实际数据进行最终确认。
  </div>
</div>
</body>
</html>
"""


def render_html(
    records: list[RetirementRecord],
    today: date,
    target: date,
) -> str:
    new_models = [r for r in records if r.is_new]
    conflicts = [r for r in records if r.conflict == "Yes"]
    deprecated = [r for r in records if "deprecat" in r.lifecycle.lower()]

    if not records:
        table_html = '<div class="empty">未来 30 天内没有匹配的模型退役记录。</div>'
    else:
        rows = []
        for r in records:
            cls = []
            if r.is_new:
                cls.append("is-new")
            if r.conflict == "Yes":
                cls.append("is-conflict")
            row_class = f' class="{" ".join(cls)}"' if cls else ""

            lifecycle_badge = (
                '<span class="badge deprecated">Deprecated</span>'
                if "deprecat" in r.lifecycle.lower()
                else '<span class="badge ga">{}</span>'.format(r.lifecycle or "GA")
            )
            conflict_badge = (
                '<span class="badge conflict">Yes</span>'
                if r.conflict == "Yes"
                else '<span class="badge ok">No</span>'
            )
            new_badge = '<span class="badge new">NEW</span> ' if r.is_new else ""
            note_html = (
                f'<div class="note">{r.conflict_note}</div>'
                if r.conflict == "Yes" and r.conflict_note
                else ""
            )

            rows.append(
                f"<tr{row_class}>"
                f"<td>{new_badge}{r.model}</td>"
                f"<td class='nowrap'>{r.version or '-'}</td>"
                f"<td>{lifecycle_badge}</td>"
                f"<td class='nowrap'>{r.retirement_date or r.raw_retirement_date or '-'}</td>"
                f"<td>{r.replacement or '<i style=color:#94a3b8>—</i>'}</td>"
                f"<td>{conflict_badge}{note_html}</td>"
                f"</tr>"
            )

        table_html = (
            "<table>"
            "<thead><tr>"
            "<th>Model</th><th class='nowrap'>Version</th><th>Lifecycle</th>"
            "<th class='nowrap'>Retirement date</th><th>Replacement</th><th>Conflict</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )

    new_note_html = ""
    if new_models:
        names = "、".join(
            f"{r.model} ({r.version})" if r.version else r.model for r in new_models
        )
        new_note_html = f'<div class="new-note">📌 今日新增模型：{names}</div>'

    mapping = {
        "{current_date}": today.isoformat(),
        "{target_date}": target.isoformat(),
        "{generated_at}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "{total}": str(len(records)),
        "{new_count}": str(len(new_models)),
        "{conflict_count}": str(len(conflicts)),
        "{deprecated_count}": str(len(deprecated)),
        "{source}": SOURCE_URL,
        "{table_html}": table_html,
        "{new_note_html}": new_note_html,
    }
    out = HTML_TEMPLATE
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out


# ----------------------------- 主流程 -----------------------------

def main() -> int:
    today = date.today()
    target = today + timedelta(days=WINDOW_DAYS)
    print(f"[INFO] 窗口: {today} → {target}")

    html = fetch_html()
    all_records = parse_tables(html)
    print(f"[INFO] 解析到 {len(all_records)} 条原始记录")

    window_records = filter_window(all_records, today, target)
    print(f"[INFO] 窗口内 {len(window_records)} 条")

    detect_conflicts(window_records)
    yesterday = load_yesterday()
    diff_with_yesterday(window_records, yesterday)
    window_records = sort_records(window_records)

    html_out = render_html(window_records, today, target)
    OUTPUT_HTML.write_text(html_out, encoding="utf-8")
    save_today(window_records)

    print(f"[DONE] 报告: {OUTPUT_HTML}")
    print(f"[DONE] 历史: {HISTORY_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
