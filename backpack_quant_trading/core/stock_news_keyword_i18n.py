"""
财经关键词中英互配：用户输入中文时，匹配雅虎等英文源会自动带上英文同义词。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Set, Tuple

_ASCII_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.^=-]{0,11}$")

WATCH_ALL_US_ALIASES = frozenset(
    {"*", "全美股", "all", "all_us", "美股", "美股全境", "所有美股", "全部美股"}
)


def is_watch_all_us_stocks(watch_names: Iterable[str]) -> bool:
    """自选含「全美股」类通配时，不限具体 ticker，由影响面词过滤。"""
    allow = {a.casefold() for a in WATCH_ALL_US_ALIASES}
    for raw in watch_names:
        name = str(raw).strip()
        if name and name.casefold() in allow:
            return True
    return False

# 中文/英文主键 -> 所有可命中子串（含原词，大小写不敏感）
TERM_ALIASES: Dict[str, Tuple[str, ...]] = {
    # 默认影响面
    "财报": ("财报", "earnings", "financial results", "quarterly results", "annual results"),
    "业绩": ("业绩", "earnings", "results", "performance"),
    "指引": ("指引", "guidance", "outlook", "forecast"),
    "预增": ("预增", "profit warning upgrade", "raised guidance"),
    "预减": ("预减", "profit warning", "lowered guidance"),
    "亏损": ("亏损", "loss", "losses", "net loss"),
    "盈利": ("盈利", "profit", "profitable", "net income"),
    "并购": ("并购", "merger", "M&A", "acquisition"),
    "收购": ("收购", "acquisition", "acquire", "takeover", "buyout"),
    "拆分": ("拆分", "stock split", "split"),
    "回购": ("回购", "buyback", "share repurchase", "repurchase"),
    "减持": ("减持", "sell-off", "reduced stake", "cut stake"),
    "增持": ("增持", "increased stake", "raised stake", "added stake"),
    "裁员": ("裁员", "layoff", "layoffs", "job cuts", "workforce reduction"),
    "罢工": ("罢工", "strike", "strikes"),
    "获批": ("获批", "approval", "approved", "cleared"),
    "被拒": ("被拒", "rejected", "denied", "rejection"),
    "诉讼": ("诉讼", "lawsuit", "litigation", "sued", "sue"),
    "调查": ("调查", "investigation", "probe", "inquiry"),
    "停牌": ("停牌", "trading halt", "suspended"),
    "复牌": ("复牌", "resume trading", "trading resumes"),
    "破产": ("破产", "bankruptcy", "chapter 11"),
    "违约": ("违约", "default", "breach"),
    "闪崩": ("闪崩", "flash crash", "plunge"),
    "大涨": ("大涨", "surge", "soar", "rally", "jump"),
    "大跌": ("大跌", "plunge", "tumble", "slump", "drop"),
    "涨超": ("涨超", "surge", "gain", "rally"),
    "跌超": ("跌超", "fall", "drop", "decline", "slump"),
    "超预期": (
        "超预期",
        "beat expectations",
        "beats expectations",
        "beat estimates",
        "beats estimates",
        "above expectations",
        "better than expected",
        "topped estimates",
    ),
    "不及预期": (
        "不及预期",
        "miss expectations",
        "missed expectations",
        "miss estimates",
        "below expectations",
        "worse than expected",
    ),
    "目标价": ("目标价", "price target", "target price"),
    "评级": ("评级", "rating", "upgrade", "downgrade", "initiated"),
    "突发": ("突发", "breaking", "unexpected"),
    "召回": ("召回", "recall"),
    "制裁": ("制裁", "sanctions", "sanction"),
    "禁令": ("禁令", "ban", "banned"),
    "加息": ("加息", "rate hike", "raised rates"),
    "降息": ("降息", "rate cut", "cut rates"),
    "利率决议": ("利率决议", "rate decision", "FOMC", "fed decision"),
    "原油": ("原油", "crude oil", "oil price"),
    "FDA": ("FDA", "FDA"),
    "NMPA": ("NMPA", "NMPA"),
    "OPEC": ("OPEC", "OPEC"),
    # 用户常见扩展词
    "业绩超预期": (
        "业绩超预期",
        "beat expectations",
        "beats expectations",
        "earnings beat",
        "earnings beats",
        "tops estimates",
        "top estimates",
        "exceeded estimates",
    ),
    "营收增长": ("营收增长", "revenue growth", "sales growth", "revenue rose", "revenue increase"),
    "净利润增长": ("净利润增长", "net income growth", "profit growth", "earnings growth"),
    "订单大增": ("订单大增", "orders surge", "order growth", "bookings surge", "backlog growth"),
    "新客户合作": ("新客户合作", "new customer", "customer win", "partnership", "strategic deal"),
    "新产品发布": ("新产品发布", "new product", "product launch", "unveiled"),
    "技术突破": ("技术突破", "breakthrough", "technology breakthrough"),
    "专利获批": ("专利获批", "patent granted", "patent approved"),
    "并购重组": ("并购重组", "merger", "acquisition", "M&A", "takeover"),
    "回购股份": ("回购股份", "buyback", "share repurchase", "repurchase program"),
    "提高股息": ("提高股息", "dividend increase", "raised dividend", "hikes dividend"),
    "机构上调评级": ("机构上调评级", "upgrade", "upgrades", "upgraded", "raised rating", "raises rating", "outperform", "buy rating"),
    "目标价上调": ("目标价上调", "raised price target", "raises price target", "raise price target", "higher price target", "target raised", "price target raised"),
    "行业政策利好": ("行业政策利好", "policy support", "favorable policy", "subsidy", "stimulus"),
    "芯片法案": ("芯片法案", "CHIPS Act", "chip act", "semiconductor bill"),
    "产能扩张": ("产能扩张", "capacity expansion", "ramp production", "fab expansion"),
    "毛利率提升": ("毛利率提升", "gross margin expansion", "margin improvement", "higher margins"),
    "业绩不及预期": ("业绩不及预期", "missed expectations", "earnings miss", "below estimates"),
    "营收下滑": ("营收下滑", "revenue decline", "sales fell", "revenue drop"),
    "亏损扩大": ("亏损扩大", "widening loss", "loss widened", "larger loss"),
    "利润暴跌": ("利润暴跌", "profit plunge", "earnings collapse", "profit tumbled"),
    "减产": ("减产", "production cut", "cut output", "reduce production"),
    "产品召回": ("产品召回", "product recall", "recall"),
    "重大诉讼": ("重大诉讼", "lawsuit", "litigation", "legal action"),
    "反垄断调查": ("反垄断调查", "antitrust", "monopoly probe", "DOJ investigation"),
    "罚款": ("罚款", "fine", "penalty", "fined"),
    "监管立案": ("监管立案", "SEC probe", "regulatory investigation", "formal investigation"),
    "财务造假": ("财务造假", "accounting fraud", "financial fraud", "fraud"),
    "高管减持": ("高管减持", "insider selling", "executive sold", "CEO sold"),
    "大股东减持": ("大股东减持", "major shareholder sold", "stake sale", "block sale"),
    "机构下调评级": ("机构下调评级", "downgrade", "downgrades", "downgraded", "cut rating", "cuts rating", "underperform", "sell rating"),
    "目标价下调": ("目标价下调", "lowered price target", "lowers price target", "lower price target", "cut price target", "target cut", "price target cut"),
    "债务违约": ("债务违约", "debt default", "default on debt"),
    "供应链中断": ("供应链中断", "supply chain disruption", "supply shortage", "supply constraint"),
    "火灾事故": ("火灾事故", "fire", "plant fire", "factory fire"),
    "停产停工": ("停产停工", "shutdown", "halt production", "plant shutdown"),
    "行业政策利空": ("行业政策利空", "regulatory crackdown", "policy headwind", "restrictions"),
    "财报发布": ("财报发布", "earnings report", "earnings release", "quarterly earnings"),
    "业绩预告": ("业绩预告", "earnings preview", "profit warning", "guidance"),
    "股东大会": ("股东大会", "shareholder meeting", "annual meeting"),
    "定增融资": ("定增融资", "private placement", "secondary offering", "capital raise"),
    "限售股解禁": ("限售股解禁", "lock-up expiry", "share unlock", "lockup expiration"),
    "股份质押": ("股份质押", "share pledge", "pledged shares"),
    "股东变更": ("股东变更", "change of control", "new shareholder", "stake change"),
    "管理层变动": ("管理层变动", "management change", "CEO change", "executive departure"),
    "行业峰会": ("行业峰会", "industry summit", "conference"),
    "技术路线变更": ("技术路线变更", "technology shift", "pivot", "roadmap change"),
    "供应链调整": ("供应链调整", "supply chain shift", "reshoring", "supplier change"),
}

# 公司/自选中文名 -> 代码与英文名
COMPANY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "英伟达": ("英伟达", "NVDA", "Nvidia", "NVIDIA"),
    "辉达": ("辉达", "NVDA", "Nvidia"),
    "英特尔": ("英特尔", "INTC", "Intel"),
    "美光": ("美光", "MU", "Micron"),
    "闪迪": ("闪迪", "SNDK", "SanDisk", "Western Digital", "WDC"),
    "西部数据": ("西部数据", "WDC", "Western Digital"),
    "苹果": ("苹果", "AAPL", "Apple"),
    "微软": ("微软", "MSFT", "Microsoft"),
    "美满": ("美满", "MRVL", "Marvell"),
    "诺基亚": ("诺基亚", "NOK", "Nokia"),
    "Rocket Lab": ("Rocket Lab", "RKLB", "火箭实验室"),
    "IBM": ("IBM", "国际商业机器"),
    "谷歌": ("谷歌", "GOOG", "GOOGL", "Google", "Alphabet"),
    "亚马逊": ("亚马逊", "AMZN", "Amazon"),
    "特斯拉": ("特斯拉", "TSLA", "Tesla"),
    "台积电": ("台积电", "TSM", "TSMC"),
    "阿斯麦": ("阿斯麦", "ASML", "ASML"),
    "高通": ("高通", "QCOM", "Qualcomm"),
    "超威": ("超威", "AMD"),
    "AMD": ("AMD", "超威"),
    "纳斯达克": ("纳斯达克", "Nasdaq", "^IXIC", "NDX"),
    "标普": ("标普", "S&P", "^GSPC", "SPX"),
    "道琼斯": ("道琼斯", "Dow", "^DJI", "DJIA"),
}

_ALIAS_INDEX: Dict[str, Tuple[str, ...]] = {}


def _build_index() -> None:
    if _ALIAS_INDEX:
        return
    for table in (TERM_ALIASES, COMPANY_ALIASES):
        for key, aliases in table.items():
            bucket: Set[str] = set(_ALIAS_INDEX.get(key, ()))
            bucket.add(key)
            bucket.update(aliases)
            for a in aliases:
                _ALIAS_INDEX[a.casefold()] = tuple(sorted(bucket, key=len, reverse=True))
            _ALIAS_INDEX[key.casefold()] = tuple(sorted(bucket, key=len, reverse=True))


def expand_terms(terms: Iterable[str]) -> List[str]:
    """将用户输入的关键词展开为中文+英文同义词列表（去重）。"""
    _build_index()
    out: List[str] = []
    seen: Set[str] = set()
    for raw in terms:
        t = str(raw).strip()
        if not t:
            continue
        variants = _ALIAS_INDEX.get(t.casefold())
        if variants:
            for v in variants:
                k = v.casefold()
                if k not in seen:
                    seen.add(k)
                    out.append(v)
            continue
        # 无映射：保留原词；纯 ASCII 视为已是英文代码
        k = t.casefold()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def watch_names_to_yahoo_queries(watch_names: Iterable[str], *, max_queries: int = 8) -> List[str]:
    """自选词展开后提取适合 Yahoo search API 的代码/短词。

    全美股通配时返回空列表，由 feeds 层走 RSS 宽表而非搜「全美股」。
    """
    import re

    names = [str(x).strip() for x in watch_names if str(x).strip()]
    if is_watch_all_us_stocks(names):
        return []

    out: List[str] = []
    seen: Set[str] = set()
    for raw in watch_names:
        w = str(raw).strip()
        if not w:
            continue
        candidates = expand_terms([w])
        picked = False
        for term in candidates:
            t = str(term).strip()
            if not t:
                continue
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9.^=-]{0,11}", t):
                key = t.upper() if t.isalpha() and len(t) <= 6 else t
                kf = key.casefold()
                if kf not in seen:
                    seen.add(kf)
                    out.append(key)
                    picked = True
        if not picked and w.casefold() not in seen:
            seen.add(w.casefold())
            out.append(w)
        if len(out) >= max_queries:
            break
    return out[:max_queries]


def _is_ascii_ticker(term: str) -> bool:
    return bool(_ASCII_TICKER_RE.match((term or "").strip()))


def _term_in_text(text_cf: str, term: str, *, strict_ticker: bool = False) -> bool:
    raw = (term or "").strip()
    if not raw:
        return False
    key = raw.casefold()
    if strict_ticker and _is_ascii_ticker(raw):
        pat = r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])"
        return bool(re.search(pat, text_cf))
    if key in text_cf:
        return True
    parts = [p for p in key.split() if len(p) > 2]
    if len(parts) >= 2:
        return all(p in text_cf or f"{p}s" in text_cf or f"{p}ed" in text_cf for p in parts)
    if len(key) > 3:
        stem = key.rstrip("s")
        if stem != key and f"{stem}s" in text_cf:
            return True
        if f"{key}s" in text_cf:
            return True
    return False


def text_matches_any_term(text: str, terms: Iterable[str]) -> bool:
    if not text:
        return False
    expanded = expand_terms(terms)
    t = text.casefold()
    return any(_term_in_text(t, kw) for kw in expanded if kw)


def text_matches_watch_terms(text: str, terms: Iterable[str]) -> bool:
    """自选代码用边界匹配，避免 MU 误命中 MUFG 等。"""
    if not text:
        return False
    expanded = expand_terms(terms)
    t = text.casefold()
    return any(
        _term_in_text(t, kw, strict_ticker=_is_ascii_ticker(kw)) for kw in expanded if kw
    )
