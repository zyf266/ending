"""一次性脚本：将 2026-05-16 激进版周报写入 us_bubble_history.json（保留历史）。"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent
HISTORY = DATA / "us_bubble_history.json"

NEW_REPORT = {
    "generated_at_utc": "2026-05-16T10:00:00Z",
    "report_date": "2026-05-16",
    "report_label": "宏观警报拉响 · 5/20 NVDA战役",
    "bubble_total_score": 41,
    "bubble_total_max": 70,
    "short_term_score": 17,
    "short_term_max": 20,
    "mid_term_score": 13,
    "mid_term_max": 25,
    "long_term_score": 11,
    "long_term_max": 25,
    "stage": "1999 叙事和估值同步加速",
    "stage_probabilities": {
        "1996-1998 早期扩散": 0.0,
        "1999 叙事和估值同步加速": 0.50,
        "2000Q1 顶部附近": 0.35,
        "2000H2 订单和资本开支恶化": 0.10,
        "2001-2002 信用风险暴露": 0.05,
        "2003+ 幸存者阶段": 0.0,
    },
    "market_state": "顶部加速但宏观裂痕加深",
    "next_week_bias": "激进持有+对冲",
    "short_term_bias": "激进持有核心但增加对冲",
    "mid_term_bias": "持有核心龙头，6月SpaceX IPO后重新评估",
    "analog_year": "1999年Q4加速赶顶期",
    "key_invalidation": "（1）NVDA 5/20财报营收低于420亿美元或毛利率低于70%；（2）10年期美债收益率突破5%；（3）SOX跌破11000且无法在3个交易日内收复。以上触发任何一项，立即转入「2000年Q1」防御模式。",
    "one_liner": "激进但不鲁莽——坚定持有NVDA+MU迎接5/20财报，SOX 11000为唯一机械止损锚，现金储备升至15%以防加息+油价双重挤压。",
    "is_seed": True,
    "report": {
        "top5_events": [
            {
                "id": 1,
                "title": "油价飙至109美元+美债10年期突破4.6%+加息预期飙至60%",
                "fact": "5月15日WTI收于105.42美元（+4.2%），布伦特收于109.26美元（+3.35%）。10年期美债收益率大涨11.27个基点报4.593%，盘中一度触及4.599%。30年期收益率收于5.117%，为2007年7月以来最高。CME FedWatch显示，市场定价到2027年1月加息概率已升至约60%。",
                "source_date": "中新经纬/搜狐/富途/163.com，2026年5月16日",
                "why_matters": "油价破109+30年期美债破5.13%+加息预期从一周前13.6%飙至60%，构成经典的通胀驱动加息恐慌传导链。周五情绪逆转表明宏观利空积累已触及阈值。",
                "direction": "对高杠杆/高估值/无盈利AI标的构成持续性杀伤，NVDA/MU因盈利支撑相对免疫但无法完全脱钩",
                "plan_change": "是——上周满仓进攻需微调为重仓但保留现金缓冲+增加对冲",
            },
            {
                "id": 2,
                "title": "SOX单日暴跌4.02%——芯片股屠榜日但NVDA全周仍涨近5%",
                "fact": "SOX周五暴跌4.02%至11588.46，周跌幅1.59%。ARM跌超8%，美光跌超6%，英特尔跌超6%，AMD跌超5%。NVDA全周仍涨近5%，周五收跌4.42%，成交402亿美元居全市场第一。",
                "source_date": "同花顺iFinD/21世纪经济报道/Investopedia，2026年5月16日",
                "why_matters": "周五暴跌是品质筛选而非系统性崩塌。资金不是逃离半导体，是在内部做极端优胜劣汰，INTC和SNDK被系统性抛弃。",
                "direction": "加速资金向NVDA和MU集中",
                "plan_change": "是——坚决清仓INTC和SNDK；NVDA和MU核心持有逻辑反被强化",
            },
            {
                "id": 3,
                "title": "VIX在SPY仅跌1.2%时跳涨6.78%",
                "fact": "VIX从周四17.87跳升至周五18.43（+6.78%），SPY仅跌1.2%。白银单日暴跌10.15%，Put/Call比率回升。",
                "source_date": "Titan Protect/TrendSpider，2026年5月16日",
                "why_matters": "期权市场在为下周一更糟定价，波动率市场发出本轮牛市中最明确的短期警告。",
                "direction": "短期下行风险定价升高，Put保护必要性同步提升",
                "plan_change": "是——NVDA的Put保护从建议升级为必须配置",
            },
            {
                "id": 4,
                "title": "Anthropic以9000亿美元估值敲定300亿美元融资",
                "fact": "5月15日Anthropic与红杉、Dragoneer等敲定300亿美元融资条款，投后估值约9000亿美元。年化收入约300亿美元，毛利率约40%，2026年训练成本预计190亿美元。",
                "source_date": "金融时报/36氪/腾讯科技，2026年5月15-17日",
                "why_matters": "一级市场仍在加速定价AI，短期利好基础设施订单，中期IPO管道构成抽水压力。",
                "direction": "短期利好NVDA/谷歌云，中期抽水压力升级",
                "plan_change": "否——强化持有NVDA，但6月后需重新评估",
            },
            {
                "id": 5,
                "title": "SpaceX IPO提前至6月12日",
                "fact": "SpaceX计划6月12日纳斯达克上市（SPCX），最早5月20日公布招股书。融资目标约750亿美元，估值1.75万亿美元。",
                "source_date": "财联社/搜狐/湾区财经，2026年5月16日",
                "why_matters": "与5/20 NVDA财报形成双重事件叠加，增加波动率；但长期对AI板块有光环效应。",
                "direction": "短期增加事件风险，中期抬高板块关注度",
                "plan_change": "否——用Put保护可管理，6月后重新评估流动性",
            },
        ],
        "score_short": [
            {"dim": "估值极端度", "score": 4, "max": 5, "basis": "SOX仍较200日均线偏离60%+，周五跌4%是压力释放非结构恶化"},
            {"dim": "市场宽度与动量拥挤", "score": 5, "max": 5, "basis": "成交额前20仅4家上涨15家下跌，极端大票普跌格局"},
            {"dim": "信用与流动性预警", "score": 3, "max": 5, "basis": "加息预期一周内从13.6%飙至60%，VIX异常跳涨"},
            {"dim": "事件催化剂风险", "score": 5, "max": 5, "basis": "SpaceX招股书+Anthropic融资+5/20 NVDA财报+FOMC会议纪要四重叠加"},
        ],
        "score_short_total": 17,
        "score_short_max": 20,
        "score_short_conclusion": "已现下跌引信，但引信长度足以撑过5/20财报；本周五抛售是预警而非终结。",
        "score_mid": [
            {"dim": "资本开支过热程度", "score": 3, "max": 5, "basis": "四大巨头年度Capex约7250亿美元，但谷歌云积压订单翻倍证实需求存在"},
            {"dim": "融资脆弱性", "score": 3, "max": 5, "basis": "Anthropic 9000亿+SpaceX 1.75万亿+OpenAI 8520亿=3.5万亿IPO管道；Meta发债200-250亿"},
            {"dim": "真实需求边际变化", "score": 2, "max": 5, "basis": "谷歌云+63%无减速，但Anthropic毛利率仅40%"},
            {"dim": "供给瓶颈缓解信号", "score": 1, "max": 5, "basis": "台积电2纳米、HBM售罄至2027年，无缓解信号"},
            {"dim": "龙头盈利质量拐点", "score": 2, "max": 5, "basis": "NVDA全周仍涨近5%，盈利叙事未破"},
            {"dim": "Capex回报率边际递减", "score": 2, "max": 5, "basis": "亚马逊FCF同比-95%、Alphabet -47%是重要警告"},
        ],
        "score_mid_total": 13,
        "score_mid_max": 25,
        "score_mid_conclusion": "泡沫健康加速但出现第一道裂缝——自由现金流转负迫使巨头举债维持Capex。",
        "score_long": [
            {"dim": "监管与地缘重构", "score": 3, "max": 5, "basis": "美伊战争持续，油价破109，霍尔木兹海峡仍实质关闭"},
            {"dim": "Mega IPO与私募抽水", "score": 3, "max": 5, "basis": "SpaceX提前至6/12，Anthropic 9000亿估值"},
            {"dim": "二三线公司脆弱性", "score": 3, "max": 5, "basis": "ARM、英特尔、高通等二线被系统性抛弃"},
            {"dim": "技术路线颠覆风险", "score": 1, "max": 5, "basis": "无替代方案达到GPT-5/Claude Opus 4水平"},
            {"dim": "信用市场结构性压力", "score": 1, "max": 5, "basis": "HY OAS仍处低位，Meta发债尚属个案"},
        ],
        "score_long_total": 11,
        "score_long_max": 25,
        "score_long_conclusion": "1999年Q4加速赶顶期，但向2000年Q1过渡速度在加快。",
        "synthesis": [
            {"label": "短期建议（1-4周）", "value": "激进持有核心但增加对冲。5/20 NVDA财报是唯一焦点，正股重仓+Put保护+15%现金缓冲。SOX 11000为唯一机械止损锚。"},
            {"label": "中期建议（3-6个月）", "value": "持有核心龙头，6月SpaceX IPO后重新评估。自由现金流转负+债务融资Capex是中期最重要风险信号。"},
            {"label": "长期类比年份", "value": "1999年Q4加速赶顶期——享受最后主升浪但随时准备右侧离场。"},
            {"label": "短期最关键反证条件", "value": "NVDA 5/20财报营收<420亿或毛利率<70%；10年期美债突破5%；SOX跌破11000且三日不收复。"},
        ],
        "positions": [
            {
                "code": "NVDA",
                "status": "周前四七连涨推全周涨近5%，周五跌4.42%，成交402亿全市场第一",
                "risk_change": "5/20财报前仓位集中风险达峰值；VIX异常跳涨",
                "action": "正股满仓（50-55%）+5/20到期$215-220的5% OTM Put",
                "trigger": "周一开盘执行；SOX跌破11000执行50%减仓",
                "invalidation": "5/20财报营收<420亿或毛利率<70%次日清仓",
                "watch": "期权IV、Blackwell出货、5/20财报（预期~441亿，超470亿=加仓）",
            },
            {
                "code": "INTC",
                "status": "周五暴跌6.18%，为SOX跌幅最大标的之一",
                "risk_change": "被系统性抛弃，双催化已完全兑现",
                "action": "清仓，全部卖出",
                "trigger": "周一开盘立即执行",
                "invalidation": "若宣布NVIDIA/Google级大客户代工合同再评估",
                "watch": "清仓后不再关注",
            },
            {
                "code": "MU",
                "status": "周五跌6.62%，成交351亿全市场第二",
                "risk_change": "短期筹码博弈激烈，获利盘与机构接盘并存",
                "action": "持有核心仓位（15-20%），设$720硬止损",
                "trigger": "MU跌至$720或SOX跌破11000减仓50%",
                "invalidation": "HBM客户砍单传闻则重新评估",
                "watch": "MU期权成交量、HBM价格、存储现货价",
            },
            {
                "code": "SNDK",
                "status": "周五跌超6%，Q2财报后不确定性未消退",
                "risk_change": "出货量走弱+SOX暴跌中继续被惩罚性抛售",
                "action": "清仓，全部卖出",
                "trigger": "周一开盘立即执行",
                "invalidation": "若Q3指引超预期再评估",
                "watch": "清仓后不再关注",
            },
        ],
        "scenarios": [
            {
                "name": "情景一：周五抛售被完全消化",
                "probability": 0.25,
                "trigger": "周末美伊缓和+周一SOX反弹2%+10年期美债回落至4.5%下方",
                "do": "保持NVDA满仓+MU持有；VIX回落至17以下可减少部分Put；现金缓冲从15%降至10%",
                "dont": "不要因一天反弹就清仓Put、不要追高二线芯片股",
            },
            {
                "name": "情景二：宏观阴云持续+高位震荡（基准）",
                "probability": 0.55,
                "trigger": "油价100-110、10年期4.5-4.6%、SOX在11000-11800震荡",
                "do": "NVDA满仓+Put不变；MU持有+$720止损；INTC/SNDK周一清仓；15%现金",
                "dont": "不要震荡追高、不要抄底二线芯片、不要因VIX恐慌清仓",
            },
            {
                "name": "情景三：多重利空共振",
                "probability": 0.20,
                "trigger": "布伦特突破120+10年期突破5%+SOX跌破11000且三日不收复",
                "do": "NVDA减仓50%+Put保留；MU减仓50%；清仓INTC/SNDK；敞口降至40%以下",
                "dont": "不要在SOX破关键位时抄底、不要保持裸多",
            },
        ],
        "actions": [
            {"idx": 1, "action": "NVDA正股满仓+买入$215-220 Put", "target": "NVDA + May20 Put", "reason": "5/20财报是年度最重要催化剂；Put锁死尾部风险保留上行空间", "trigger": "周一开盘；若再跌2-3% Put成本更低", "stop": "仅财报不及预期时清仓", "period": "持有至5/20盘后"},
            {"idx": 2, "action": "坚决清仓INTC", "target": "INTC", "reason": "周五暴跌6.18%，华尔街目标价远低于现价", "trigger": "周一开盘立即执行", "stop": "—", "period": "一次性"},
            {"idx": 3, "action": "坚决清仓SNDK", "target": "SNDK", "reason": "出货量环比下降+分析师卖出评级", "trigger": "周一开盘立即执行", "stop": "—", "period": "一次性"},
            {"idx": 4, "action": "MU持有+$720硬止损", "target": "MU", "reason": "HBM售罄至2027年，但短期多空分歧极大", "trigger": "当前持有；跌破$720减仓50%", "stop": "HBM砍单则全仓重评", "period": "至5/20财报后"},
            {"idx": 5, "action": "买入SOXX/SMH宏观对冲Put", "target": "SOXX/SMH Put", "reason": "宏观风险已从噪音升级为实质威胁", "trigger": "SOX反弹至11600-11800建仓", "stop": "—", "period": "至5/20"},
            {"idx": 6, "action": "保留15%现金缓冲", "target": "现金", "reason": "加息+油价+VIX异常组合下保留弹药", "trigger": "清仓INTC/SNDK释放资金后", "stop": "财报超预期可用10%加仓", "period": "至5/20"},
            {"idx": 7, "action": "每日监控10年期美债+HY OAS", "target": "利率/信用", "reason": "10年期破5%将压缩估值体系", "trigger": "持续监控", "stop": "破5%或HY OAS破3%则敞口降至50%以下", "period": "持续"},
            {"idx": 8, "action": "5/20 NVDA财报机动方案", "target": "全组合", "reason": ">470亿加仓；420-470亿持有；<420亿清仓", "trigger": "5/20盘后", "stop": "—", "period": "5/20当日"},
        ],
        "watch_points": [
            {"idx": 1, "point": "5/20 NVDA FY2027 Q1财报", "detail": ">470亿加仓；420-470亿持有；<420亿清仓", "stars": 5},
            {"idx": 2, "point": "10年期美债4.6-5.0%", "detail": "突破4.75%估值承压；突破5%全面降敞口", "stars": 5},
            {"idx": 3, "point": "SOX 11000关键位", "detail": "跌破且三日不收复=技术面恶化", "stars": 5},
            {"idx": 4, "point": "SpaceX招股书（最早5/20）", "detail": "与NVDA财报双重事件叠加", "stars": 4},
            {"idx": 5, "point": "美伊局势+WTI原油", "detail": "油价破115-120=通胀螺旋风险", "stars": 4},
            {"idx": 6, "point": "CME FedWatch加息概率", "detail": "升至75%+将构成估值结构性重置", "stars": 4},
            {"idx": 7, "point": "FOMC 5月会议纪要", "detail": "鹰派人数超预期=加息预期飙升", "stars": 4},
            {"idx": 8, "point": "Anthropic 300亿融资签约", "detail": "确认一级市场继续扩张叙事", "stars": 3},
            {"idx": 9, "point": "MU $720止损线", "detail": "触及无条件减仓50%", "stars": 5},
            {"idx": 10, "point": "白银暴跌后续", "detail": "若金银继续重挫或预示广泛流动性撤离", "stars": 3},
        ],
        "core_summary": "本周是「宏观警报全面拉响但AI盈利叙事维持完整」的一周。油价破109、10年期飙至4.6%、加息预期飙至60%，周五SOX暴跌4.02%。但NVDA全周仍涨近5%，INTC/SNDK被抛弃。策略：NVDA满仓+Put+15%现金；MU持有$720止损；INTC/SNDK清仓。5/20 NVDA财报是唯一焦点。SOX 11000为机械止损锚。风险评分41/70。",
    },
    "markdown": "",
}


def main() -> None:
    items: list = []
    if HISTORY.is_file():
        items = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            items = []
    # 避免重复导入
    gid = NEW_REPORT["generated_at_utc"]
    items = [x for x in items if (x.get("generated_at_utc") or "") != gid]
    items.append(NEW_REPORT)
    HISTORY.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ok: {len(items)} reports in {HISTORY}")


if __name__ == "__main__":
    main()
