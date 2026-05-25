"""AI 选股 PDF 研报卡片与结构化正文（多标的）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA = Path(__file__).resolve().parents[1] / "data"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _DATA / "research_cards_registry.json"


def _load_registry() -> List[Dict[str, str]]:
    if not _REGISTRY.is_file():
        return []
    raw = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    cards = raw.get("cards") if isinstance(raw, dict) else raw
    if not isinstance(cards, list):
        return []
    out = []
    for c in cards:
        if isinstance(c, dict) and c.get("code"):
            out.append(
                {
                    "code": str(c["code"]).upper().strip(),
                    "card_file": str(c.get("card_file") or ""),
                    "report_file": str(c.get("report_file") or ""),
                }
            )
    return out


def list_research_codes() -> List[str]:
    return [x["code"] for x in _load_registry()]


def _entry_for_code(code: str) -> Optional[Dict[str, str]]:
    k = str(code or "").upper().strip()
    for e in _load_registry():
        if e["code"] == k:
            return e
    return None


def load_research_card(code: str) -> Dict[str, Any]:
    entry = _entry_for_code(code)
    if not entry or not entry.get("card_file"):
        raise FileNotFoundError(f"未注册研究卡片: {code}")
    path = _DATA / entry["card_file"]
    if not path.is_file():
        raise FileNotFoundError(f"卡片数据不存在: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_research_report(code: str) -> Dict[str, Any]:
    entry = _entry_for_code(code)
    if not entry or not entry.get("report_file"):
        raise FileNotFoundError(f"未注册研报: {code}")
    path = _DATA / entry["report_file"]
    if not path.is_file():
        raise FileNotFoundError(f"研报数据不存在: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "code": data.get("code", code),
        "name": data.get("name", ""),
        "tagline": data.get("tagline", ""),
        "institution": data.get("institution", "沐龙量化研究"),
        "report_date": data.get("report_date", ""),
        "sections": data.get("sections") or [],
        "conclusion": data.get("conclusion", ""),
    }


def resolve_pdf_path(code: str) -> Path:
    card = load_research_card(code)
    rel = str(card.get("pdf_path") or "").strip()
    if not rel:
        raise FileNotFoundError(f"未配置 PDF 路径: {code}")
    pdf = _PROJECT_ROOT / rel
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF 文件不存在: {rel}")
    return pdf


def get_quote_symbol(code: str) -> str:
    try:
        card = load_research_card(code)
        return str(card.get("quote_symbol") or card.get("code") or code).upper()
    except FileNotFoundError:
        return str(code).upper()
