"""
Azure AI Foundry 模型退役监控 - 核心模块（云端可复用）
- 抓取退役日程页面
- 解析 / 时间过滤 / 冲突检测 / 与昨日 diff
- 渲染美观且自适应的邮件 HTML
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

# ----------------------------- 数据模型 -----------------------------

@dataclass
class RetirementRecord:
    model: str
    version: str
    lifecycle: str
    retirement_date: str
    replacement: str
    raw_retirement_date: str = ""
    conflict: str = "No"
    conflict_note: str = ""
    is_new: bool = False

    def key(self) -> tuple[str, str]:
        return (self.model.strip().lower(), self.version.strip().lower())


# ----------------------------- 抓取 -----------------------------

FALLBACK_URLS = [
    "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule",
    "https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/model-retirement-schedule",
    "https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/model-retirements",
]


def fetch_html(source_url: str | None = None) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    urls: list[str] = []
    if source_url:
        urls.append(source_url)
    urls.extend(u for u in FALLBACK_URLS if u not in urls)

    last_err: Exception | None = None
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.encoding = "utf-8"
            if resp.status_code == 200 and "retire" in resp.text.lower():
                return resp.text
            last_err = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"全部数据源抓取失败: {last_err}")


# ----------------------------- 日期解析 -----------------------------

DATE_FORMATS = [
    "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d",
    "%m/%d/%Y", "%d %B %Y", "%d %b %Y",
]


def parse_date(text: str) -> Optional[date]:
    if not text:
        return None
    s = re.sub(r"\s+", " ", text).strip().rstrip(".")
    s = re.sub(
        r"(?i)(no earlier than|at the earliest|on or after|after|by|before)\s+",
        "", s,
    )
    m = re.search(
        r"([A-Za-z]+\s+\d{1,2},\s*\d{4}|\d{4}-\d{2}-\d{2}|"
        r"\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        s,
    )
    if m:
        s = m.group(1)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ----------------------------- 表格解析 -----------------------------

def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", h).strip().lower()


def parse_tables(html: str) -> list[RetirementRecord]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[RetirementRecord] = []

    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if not first_row:
            continue
        headers = [
            _norm(th.get_text(" ", strip=True))
            for th in first_row.find_all(["th", "td"])
        ]
        joined = " ".join(headers)
        if not ("model" in joined and "retirement" in joined):
            continue

        def find_col(*kws: str) -> int:
            for i, h in enumerate(headers):
                if all(k in h for k in kws):
                    return i
            return -1

        idx_model = find_col("model")
        idx_version = find_col("version")
        if idx_version == -1:
            idx_version = find_col("legacy")
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


# ----------------------------- 过滤/冲突/排序 -----------------------------

def filter_window(records: list[RetirementRecord], today: date, target: date) -> list[RetirementRecord]:
    out = []
    for r in records:
        d = parse_date(r.raw_retirement_date)
        if d and today <= d <= target:
            out.append(r)
    return out


def detect_conflicts(records: list[RetirementRecord]) -> None:
    groups: dict[tuple[str, str], list[RetirementRecord]] = {}
    for r in records:
        groups.setdefault(r.key(), []).append(r)
    for group in groups.values():
        if len(group) <= 1:
            continue
        dates = {r.retirement_date for r in group}
        replaces = {r.replacement for r in group}
        lifecycles = {r.lifecycle for r in group}
        if len(dates) > 1 or len(replaces) > 1 or len(lifecycles) > 1:
            for r in group:
                others = [o for o in group if o is not r]
                r.conflict = "Yes"
                r.conflict_note = " | ".join(
                    f"其他记录: 日期={o.retirement_date or '-'}, "
                    f"Lifecycle={o.lifecycle or '-'}, "
                    f"Replacement={o.replacement or '-'}"
                    for o in others
                )


def sort_records(records: list[RetirementRecord]) -> list[RetirementRecord]:
    def k(r: RetirementRecord):
        has_repl = 0 if r.replacement.strip() else 1
        d = parse_date(r.raw_retirement_date) or date.max
        return (
            has_repl,
            -d.toordinal(),
            0 if "deprecat" in r.lifecycle.lower() else 1,
            r.model.lower(),
            r.version.lower(),
        )
    return sorted(records, key=k)


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


# ----------------------------- 变化检测 -----------------------------

def has_changes(
    today_records: list[RetirementRecord],
    yesterday: list[dict[str, Any]],
) -> dict[str, Any]:
    """返回变化摘要：是否需要发邮件 + 详情。"""
    y_map: dict[tuple[str, str], dict[str, Any]] = {
        (str(r.get("model", "")).strip().lower(), str(r.get("version", "")).strip().lower()): r
        for r in yesterday
    }
    new_items: list[RetirementRecord] = []
    changed_items: list[tuple[RetirementRecord, dict[str, Any]]] = []
    today_keys = set()
    for r in today_records:
        today_keys.add(r.key())
        if r.key() not in y_map:
            new_items.append(r)
        else:
            old = y_map[r.key()]
            if (
                old.get("retirement_date") != r.retirement_date
                or old.get("replacement") != r.replacement
                or old.get("lifecycle") != r.lifecycle
                or old.get("conflict") != r.conflict
            ):
                changed_items.append((r, old))
    removed_items = [old for k, old in y_map.items() if k not in today_keys]
    return {
        "changed": bool(new_items or changed_items or removed_items),
        "new": new_items,
        "modified": changed_items,
        "removed": removed_items,
    }


# ----------------------------- 渲染（响应式邮件 HTML） -----------------------------

EMAIL_HTML = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="x-apple-disable-message-reformatting" />
<meta name="color-scheme" content="light dark" />
<meta name="supported-color-schemes" content="light dark" />
<title>未来 30 天 · Azure AI Foundry 模型退役监控</title>
<style>
  /* 仅在支持 <style> 的客户端生效；不支持的客户端会用 inline 样式回退 */
  body, table, td, p, a, li { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
  table, td { border-collapse: collapse; mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
  img { border: 0; line-height: 100%; outline: none; text-decoration: none; }
  body { margin: 0 !important; padding: 0 !important; width: 100% !important; background-color: #0f172a; }
  a { color: #38bdf8; text-decoration: none; }

  /* 手机端：≤600px 时把表格转为卡片堆叠 */
  @media screen and (max-width: 600px) {
    .container { width: 100% !important; max-width: 100% !important; }
    .px { padding-left: 16px !important; padding-right: 16px !important; }
    .stat-cell { display: block !important; width: 100% !important; padding: 6px 0 !important; }
    .data-table thead { display: none !important; }
    .data-table, .data-table tbody, .data-table tr, .data-table td {
      display: block !important; width: 100% !important; box-sizing: border-box !important;
    }
    .data-table tr {
      margin-bottom: 14px !important;
      border: 1px solid #334155 !important;
      border-radius: 10px !important;
      padding: 8px 10px !important;
      background: #1e293b !important;
    }
    .data-table td {
      border: none !important;
      padding: 4px 0 !important;
      font-size: 14px !important;
      color: #e2e8f0 !important;
    }
    .data-table td::before {
      content: attr(data-label) " : ";
      color: #94a3b8;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      display: inline-block;
      margin-right: 6px;
    }
  }

  /* 暗色模式适配（已默认暗色，保持） */
  @media (prefers-color-scheme: dark) {
    body { background-color: #0f172a !important; }
  }
</style>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,'Helvetica Neue',Arial,sans-serif;color:#e2e8f0;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#0f172a;">
  <tr>
    <td align="center" style="padding:24px 12px;">
      <table role="presentation" class="container" width="720" cellspacing="0" cellpadding="0" border="0" style="width:720px;max-width:720px;background:#1e293b;border:1px solid #334155;border-radius:14px;overflow:hidden;">
        <!-- HEADER -->
        <tr>
          <td class="px" style="padding:22px 26px;background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);border-bottom:1px solid #334155;">
            <div style="font-size:20px;font-weight:700;color:#38bdf8;margin:0 0 6px 0;">
              🛰️ Azure AI Foundry · 未来 30 天模型退役监控
            </div>
            <div style="font-size:13px;color:#94a3b8;line-height:1.7;">
              <span>📅 当前: <b style="color:#e2e8f0;">{current_date}</b></span> &nbsp;|&nbsp;
              <span>🎯 截止 (T+30): <b style="color:#e2e8f0;">{target_date}</b></span> &nbsp;|&nbsp;
              <span>🕒 {generated_at}</span>
            </div>
          </td>
        </tr>
        <!-- SHARE LINK -->
        <tr>
          <td class="px" style="padding:14px 26px 4px 26px;">
            <div style="background:rgba(56,189,248,0.10);border:1px solid #334155;border-left:3px solid #38bdf8;padding:12px 14px;border-radius:6px;font-size:13px;color:#cbd5e1;line-height:1.7;">
              🔗 <b style="color:#e2e8f0;">在线版报告（可直接分享）：</b>
              <a href="https://aka.ms/foundry-30d-retirement" style="color:#38bdf8;font-weight:600;">https://aka.ms/foundry-30d-retirement</a>
              <div style="font-size:11px;color:#94a3b8;margin-top:4px;">
                每天自动刷新的 Azure AI Foundry 未来 30 天模型退役清单。把这个短链接发给团队/客户，他们随时打开都是最新数据。
              </div>
            </div>
          </td>
        </tr>
        <!-- STATS -->
        <tr>
          <td class="px" style="padding:16px 26px 8px 26px;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
              <tr>
                <td class="stat-cell" style="padding:0 6px;" valign="top">
                  <div style="background:rgba(56,189,248,0.08);border:1px solid #334155;border-radius:10px;padding:12px 14px;">
                    <div style="font-size:22px;font-weight:700;color:#38bdf8;">{total}</div>
                    <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;">窗口内退役</div>
                  </div>
                </td>
                <td class="stat-cell" style="padding:0 6px;" valign="top">
                  <div style="background:rgba(59,130,246,0.10);border:1px solid #334155;border-radius:10px;padding:12px 14px;">
                    <div style="font-size:22px;font-weight:700;color:#93c5fd;">{new_count}</div>
                    <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;">今日新增</div>
                  </div>
                </td>
                <td class="stat-cell" style="padding:0 6px;" valign="top">
                  <div style="background:rgba(248,113,113,0.08);border:1px solid #334155;border-radius:10px;padding:12px 14px;">
                    <div style="font-size:22px;font-weight:700;color:#f87171;">{conflict_count}</div>
                    <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;">冲突记录</div>
                  </div>
                </td>
                <td class="stat-cell" style="padding:0 6px;" valign="top">
                  <div style="background:rgba(251,191,36,0.08);border:1px solid #334155;border-radius:10px;padding:12px 14px;">
                    <div style="font-size:22px;font-weight:700;color:#fbbf24;">{deprecated_count}</div>
                    <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;">Deprecated</div>
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <!-- CHANGE SUMMARY -->
        {change_summary}
        <!-- TABLE -->
        <tr>
          <td class="px" style="padding:8px 26px 4px 26px;">
            <table role="presentation" class="data-table" width="100%" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;">
              <thead>
                <tr>
                  <th align="left" style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;padding:8px 8px;border-bottom:1px solid #334155;">Model</th>
                  <th align="left" nowrap="nowrap" style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;padding:8px 8px;border-bottom:1px solid #334155;white-space:nowrap;">Version</th>
                  <th align="left" style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;padding:8px 8px;border-bottom:1px solid #334155;">Lifecycle</th>
                  <th align="left" nowrap="nowrap" style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;padding:8px 8px;border-bottom:1px solid #334155;white-space:nowrap;">Retirement</th>
                  <th align="left" style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;padding:8px 8px;border-bottom:1px solid #334155;">Replacement</th>
                  <th align="left" style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;padding:8px 8px;border-bottom:1px solid #334155;">Conflict</th>
                </tr>
              </thead>
              <tbody>
                {rows}
              </tbody>
            </table>
          </td>
        </tr>
        <!-- FOOTER -->
        <tr>
          <td class="px" style="padding:16px 26px 22px 26px;">
            <div style="background:rgba(251,191,36,0.08);border-left:3px solid #fbbf24;padding:12px 14px;border-radius:6px;font-size:12px;color:#fde68a;line-height:1.7;">
              ⚠️ <b>数据一致性声明：</b>如果存在 Model 信息与历史认知不一致、Retirement date 异常变化、或同页面字段不一致，
              该数据可能存在版本差异（Microsoft Learn 页面缓存或延迟更新），建议结合 Azure Portal 实际数据进行最终确认。
            </div>
            <div style="margin-top:12px;font-size:11px;color:#94a3b8;">
              数据源:&nbsp;<a href="{source}" style="color:#38bdf8;">{source}</a>
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""


def _badge_lifecycle(text: str) -> str:
    t = (text or "GA").strip()
    if "deprecat" in t.lower():
        return ('<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
                'background:#78350f;color:#fcd34d;font-size:11px;font-weight:600;">Deprecated</span>')
    if "preview" in t.lower():
        return ('<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
                'background:#1e3a8a;color:#bfdbfe;font-size:11px;font-weight:600;">Preview</span>')
    return ('<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
            'background:#1e293b;color:#cbd5e1;border:1px solid #334155;font-size:11px;font-weight:600;">'
            f'{t}</span>')


def _badge_conflict(yes: bool) -> str:
    if yes:
        return ('<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
                'background:#7f1d1d;color:#fecaca;font-size:11px;font-weight:600;">Yes</span>')
    return ('<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
            'background:#064e3b;color:#6ee7b7;font-size:11px;font-weight:600;">No</span>')


def render_email_html(
    records: list[RetirementRecord],
    today: date,
    target: date,
    source_url: str,
    change_summary_html: str = "",
) -> str:
    new_count = sum(1 for r in records if r.is_new)
    conflict_count = sum(1 for r in records if r.conflict == "Yes")
    deprecated_count = sum(1 for r in records if "deprecat" in r.lifecycle.lower())

    if not records:
        rows = ('<tr><td colspan="6" style="padding:24px;text-align:center;color:#94a3b8;font-size:13px;">'
                '未来 30 天内没有匹配的退役记录。</td></tr>')
    else:
        row_pieces = []
        for r in records:
            row_bg = "#1e293b"
            extra_style = ""
            if r.is_new and r.conflict == "Yes":
                row_bg = "rgba(168,85,247,0.10)"; extra_style = "font-weight:700;"
            elif r.is_new:
                row_bg = "rgba(59,130,246,0.10)"; extra_style = "font-weight:700;"
            elif r.conflict == "Yes":
                row_bg = "rgba(248,113,113,0.07)"

            new_prefix = (
                '<span style="display:inline-block;padding:2px 7px;border-radius:999px;'
                'background:#1e3a8a;color:#93c5fd;font-size:10px;font-weight:700;margin-right:6px;">NEW</span>'
                if r.is_new else ""
            )
            note = (
                f'<div style="font-size:11px;color:#fbbf24;font-style:italic;margin-top:3px;font-weight:normal;">'
                f'{r.conflict_note}</div>'
                if r.conflict == "Yes" and r.conflict_note else ""
            )
            td_base = (
                f'padding:8px 8px;border-bottom:1px solid #334155;font-size:13px;color:#e2e8f0;'
                f'vertical-align:top;{extra_style}'
            )
            version_text = (r.version or "-").replace("-", "&#8209;")
            retire_raw = r.retirement_date or r.raw_retirement_date or "-"
            retire_text = retire_raw.replace("-", "&#8209;")
            row_pieces.append(
                f'<tr style="background:{row_bg};">'
                f'<td data-label="Model" style="{td_base}">{new_prefix}{r.model}</td>'
                f'<td data-label="Version" nowrap="nowrap" style="{td_base}white-space:nowrap;">{version_text}</td>'
                f'<td data-label="Lifecycle" style="{td_base}">{_badge_lifecycle(r.lifecycle)}</td>'
                f'<td data-label="Retirement" nowrap="nowrap" style="{td_base}white-space:nowrap;">{retire_text}</td>'
                f'<td data-label="Replacement" style="{td_base}">'
                f'{r.replacement if r.replacement.strip() else "<span style=color:#94a3b8>—</span>"}</td>'
                f'<td data-label="Conflict" style="{td_base}">{_badge_conflict(r.conflict == "Yes")}{note}</td>'
                f'</tr>'
            )
        rows = "".join(row_pieces)

    return (EMAIL_HTML
        .replace("{current_date}", today.isoformat())
        .replace("{target_date}", target.isoformat())
        .replace("{generated_at}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        .replace("{total}", str(len(records)))
        .replace("{new_count}", str(new_count))
        .replace("{conflict_count}", str(conflict_count))
        .replace("{deprecated_count}", str(deprecated_count))
        .replace("{change_summary}", change_summary_html)
        .replace("{rows}", rows)
        .replace("{source}", source_url)
    )


def render_change_summary(changes: dict[str, Any]) -> str:
    """变化摘要块（顶部显示）。"""
    if not changes.get("changed"):
        return ""
    parts = []
    if changes["new"]:
        names = "、".join(
            f"{r.model} ({r.version})" if r.version else r.model
            for r in changes["new"]
        )
        parts.append(f'<div style="margin:4px 0;">📌 <b>新增 {len(changes["new"])} 条</b>：{names}</div>')
    if changes["modified"]:
        names = "、".join(
            f"{r.model} ({r.version})" if r.version else r.model
            for r, _ in changes["modified"]
        )
        parts.append(f'<div style="margin:4px 0;">✏️ <b>变更 {len(changes["modified"])} 条</b>：{names}</div>')
    if changes["removed"]:
        names = "、".join(
            f'{old.get("model","")} ({old.get("version","") or "-"})'
            for old in changes["removed"]
        )
        parts.append(f'<div style="margin:4px 0;">🗑️ <b>移除 {len(changes["removed"])} 条</b>：{names}</div>')

    body = "".join(parts)
    return f"""
        <tr>
          <td class="px" style="padding:8px 26px 0 26px;">
            <div style="background:rgba(59,130,246,0.12);border-left:3px solid #38bdf8;padding:12px 14px;border-radius:6px;font-size:13px;color:#bfdbfe;line-height:1.7;">
              <div style="font-weight:700;color:#e2e8f0;margin-bottom:4px;">📢 与昨日相比的变化</div>
              {body}
            </div>
          </td>
        </tr>
    """


# ----------------------------- 序列化辅助 -----------------------------

def to_dicts(records: list[RetirementRecord]) -> list[dict[str, Any]]:
    return [asdict(r) for r in records]
