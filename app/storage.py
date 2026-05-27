"""文件型历史快照存储。

- 路径来自 env `HISTORY_PATH`，默认 `data/history.json`（相对仓库根）。
- 单文件 JSON：`{"date": "YYYY-MM-DD", "records": [...]}`。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import foundry_monitor as fm


def _path() -> Path:
    return Path(os.environ.get("HISTORY_PATH", "data/history.json"))


def load_yesterday() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("records", [])
    except Exception as e:  # noqa: BLE001
        logging.warning("读取历史文件失败 %s: %s", p, e)
        return []


def save_today(records: list) -> None:
    p = _path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date": date.today().isoformat(), "records": fm.to_dicts(records)}
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        logging.error("写入历史文件失败 %s: %s", p, e)
