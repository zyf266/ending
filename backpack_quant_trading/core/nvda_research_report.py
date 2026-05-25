"""NVDA 完整研报（来自 PDF 结构化数据）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

_REPORT_PATH = Path(__file__).resolve().parents[1] / "data" / "nvda_research_report.json"


def load_nvda_research_report() -> Dict[str, Any]:
    if not _REPORT_PATH.is_file():
        raise FileNotFoundError("nvda_research_report.json 不存在")
    return json.loads(_REPORT_PATH.read_text(encoding="utf-8"))


def get_nvda_report_for_api() -> Dict[str, Any]:
    data = load_nvda_research_report()
    return {
        "code": data.get("code", "NVDA"),
        "name": data.get("name", "英伟达"),
        "tagline": data.get("tagline", ""),
        "institution": data.get("institution", ""),
        "report_date": data.get("report_date", ""),
        "source_pdf": data.get("source_pdf", ""),
        "sections": data.get("sections") or [],
        "conclusion": data.get("conclusion", ""),
    }
