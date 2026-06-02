"""一次性脚本：将 2026-05-25 周报（顶部震荡·偏防守）写入 us_bubble_history.json。"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent
HISTORY = DATA / "us_bubble_history.json"

NEW_REPORT = {
    "generated_at_utc": "2026-05-25T10:00:00Z",
    "report_date": "2026-05-25",
    "report_label": "顶部震荡 · OpenAI IPO周",
    "bubble_total_score": 29,
    "bubble_total_max": 70,
    "short_term_score": 12,
    "short_term_max": 20,
    "mid_term_score": 12,
    "mid_term_max": 25,
    "long_term_score": 5,
    "long_term_max": 25,
    "stage": "1999 叙事和估值同步加速",
    "stage_probabilities": {
        "1996-1998 早期扩散": 0.05,
        "1999 叙事和估值同步加速": 0.40,
        "2000Q1 顶部附近": 0.35,
        "2000H2 订单和资本开支恶化": 0.15,
        "2001-2002 信用风险暴露": 0.05,
        "2003+ 幸存者阶段": 0.0,
    },
    "market_state": "顶部震荡",
    "next_week_bias": "震荡交易（偏防守）",
    "short_term_bias": "震荡交易（偏防守）",
    "mid_term_bias": "持有核心+逐步止盈小票+准备对冲",
    "analog_year": "1999-2000年加速顶部阶段",
    "key_invalidation": "（1）AI云收入连续两季环比减速20%+；（2）OpenAI/SpaceX IPO实际完成抽水且科技股承压>3天；（3）GPU租赁价格月度环比下降。任一触发则上调泡沫评级并系统性减仓。",
    "one_liner": "震荡交易（偏防守）——保持持仓但收紧止损，等待下周OpenAI IPO实质进展和AI云收入边际信号决定是否进一步减仓。",
    "is_seed": True,
    "report": {
        "top5_events": [
            {
                "id": 1,
                "title": "OpenAI启动IPO程序——AI「Mega IPO」抽水预期正式落地",
                "fact": "OpenAI最快本周秘密递交IPO招股书草案，目标募资约600亿美元，估值超1万亿美元（3月私募8520亿）；与高盛、摩根士丹利合作。软银追加300亿美元，持股约13%。马斯克诉讼被法院驳回。",
                "source_date": "凤凰网财经、智通财经，2026-05-21",
                "why_matters": "AI泡沫从私募叙事走向二级市场抽水的标志性事件；进入发行窗口将系统性抽走流动性，冲击AI/科技股估值锚。",
                "direction": "短期利多情绪（叙事强化），中期利空流动性（抽水）；OpenAI概念股或获支撑但整体科技股中期承压",
                "plan_change": "是——顶部构筑期关键信号，触发从持有向减仓+对冲的预准备",
            },
            {
                "id": 2,
                "title": "英伟达财报——业绩超预期但前瞻信号初显",
                "fact": "Q1营收820亿美元创纪录，毛利率约75%，Q2指引910亿。应收账款升至384.66亿（前值230.65亿），营运资本变动-236.27亿。",
                "source_date": "NVIDIA 2027财年Q1财报，2026-05-21",
                "why_matters": "应收激增与营运资本恶化背离——业绩beat但客户付款周期拉长，或反映下游库存积累或定价权边际侵蚀。",
                "direction": "确认多头方向，但增加中期隐忧",
                "plan_change": "是——维持持仓但收紧止损",
            },
            {
                "id": 3,
                "title": "AI算力租赁Nebius再涨价30%——供给瓶颈未缓解",
                "fact": "5月21日Nebius宣布6月1日起上调部分NVIDIA GPU平台定价约30%，B300从6.10美元/小时提至7.85美元/小时。",
                "source_date": "新浪财经行业周报，2026-05-23",
                "why_matters": "供给端仍偏紧，与泡沫破裂初期产能过剩特征不符，是核心反证——不宜过早看空。",
                "direction": "利多GPU相关标的，支撑供给紧张→定价权→高毛利叙事",
                "plan_change": "部分改变——多头正面支撑仍在，不应做空核心GPU持仓",
            },
            {
                "id": 4,
                "title": "SOX历史级超买+半导体单日暴跌6%——动量修正风险显现",
                "fact": "SOX近25个交易日涨幅创2000年互联网泡沫以来最大；5月13日SOX一度暴跌6.8%后收跌3%；SMH较200周均线高出约150%，RSI连续两周>80。",
                "source_date": "金融界、网易、Barchart，2026-05-13至2026-05-20",
                "why_matters": "顶部震荡典型特征：极度超买后单日暴跌+快速修复，动量博弈激烈但无崩塌性抛压。",
                "direction": "短期利空动量修正，不改变中期趋势",
                "plan_change": "是——半导体持仓止盈/收紧止损，但不做空",
            },
            {
                "id": 5,
                "title": "市场宽度极度坍塌——Mag 7孤军支撑指数",
                "fact": "本周SPX涨幅几乎全部由Mag 7贡献，其余495只合计为负；SPX中位数股票距52周高点仍低13%，指数却不断创新高。",
                "source_date": "Heisenberg Report、AInvest，2026-05-12至2026-05-18",
                "why_matters": "指数新高与宽度背离——绝大多数个股已掉队，系统性风险上升。",
                "direction": "小票风险远超大票",
                "plan_change": "是——不加仓非核心，小票反弹中减仓",
            },
        ],
        "score_short": [
            {"dim": "估值极端度", "score": 3, "max": 5, "basis": "SOX近25日涨幅创2000年以来最大；SMH较200周线超150%"},
            {"dim": "市场宽度与动量拥挤", "score": 5, "max": 5, "basis": "Mag 7独撑指数，其余495只合计负贡献；中位数股距52周高点仍低13%"},
            {"dim": "信用与流动性预警", "score": 1, "max": 5, "basis": "HY OAS约2.82%，远低于4.5%-5%触发；VIX约18-19"},
            {"dim": "事件催化剂风险", "score": 3, "max": 5, "basis": "OpenAI IPO预期落地带来情绪催化，抽水效应尚未实际发生"},
        ],
        "score_short_total": 12,
        "score_short_max": 20,
        "score_short_conclusion": "已现顶部震荡特征（宽度坍塌+高度偏离），接近触发防御动作边界。",
        "score_mid": [
            {"dim": "资本开支过热程度", "score": 4, "max": 5, "basis": "Google 2026 Capex 1800-1900亿，微软约1900亿且称2027年仍将显著增加"},
            {"dim": "融资脆弱性", "score": 4, "max": 5, "basis": "OpenAI 8520亿→1万亿IPO；CoreWeave债务约140亿且Capex 300-350亿"},
            {"dim": "真实需求边际变化", "score": 2, "max": 5, "basis": "微软AI收入+123%、AWS AI>150亿、Google Cloud +63%——仍在加速"},
            {"dim": "供给瓶颈缓解", "score": 1, "max": 5, "basis": "Nebius再涨30%；美光HBM卖到2026年底——持续紧张"},
            {"dim": "龙头盈利质量拐点", "score": 1, "max": 5, "basis": "NVDA毛利率约75%稳定，但应收384.66亿、营运资本-236.27亿需警惕"},
            {"dim": "资本回报边际递减", "score": 0, "max": 5, "basis": "Capex增量收入比尚无可靠数据验证"},
        ],
        "score_mid_total": 12,
        "score_mid_max": 25,
        "score_mid_conclusion": "泡沫仍在加速——Capex与融资过热明显，但云AI收入与算力租赁尚未给出边际恶化信号。",
        "score_long": [
            {"dim": "监管与地缘", "score": 1, "max": 5, "basis": "Arm遭FTC调查；众议院访华后芯片限制——有动作非不可逆"},
            {"dim": "Mega IPO抽水", "score": 3, "max": 5, "basis": "OpenAI 1万亿、SpaceX同步筹备——预期已落地，实际发行后才构成持续失血"},
            {"dim": "二三线公司破产", "score": 0, "max": 5, "basis": "无批量破产；CoreWeave债务高但收入仍高增长"},
            {"dim": "技术路线证伪", "score": 0, "max": 5, "basis": "无替代方案全面超越"},
            {"dim": "信用市场系统性压力", "score": 1, "max": 5, "basis": "HY OAS约2.82%，远低于150bp恶化阈值"},
        ],
        "score_long_total": 5,
        "score_long_max": 25,
        "score_long_conclusion": "类似1999-2000加速顶部（IPO扎堆、估值分化、宽度坍塌），尚无条件指向2000H2破裂。",
        "synthesis": [
            {"label": "短期建议（1-4周）", "value": "震荡交易（偏防守）——保持持仓收紧止损，等OpenAI IPO进展与AI云收入边际信号。"},
            {"label": "中期建议（3-6个月）", "value": "持有核心（NVDA等）+逐步止盈小票（SNDK等）+准备对冲。"},
            {"label": "长期建议", "value": "持有核心，忽略短期波动。"},
            {"label": "最关键反证条件", "value": "AI云收入连续两季环比减速20%+；OpenAI/SpaceX IPO完成抽水；GPU租赁价月度环比下降（目前在涨）。"},
        ],
        "positions": [
            {
                "code": "INTC",
                "status": "待确认",
                "risk_change": "利好：DCAI收入50.5亿/+22%、毛利41%超预期；利空：净亏损37亿（一次性项目）",
                "action": "待填入成本后细化；成本30-40建议持有，>50建议减仓",
                "trigger": "—",
                "invalidation": "—",
                "watch": "DCAI订单可持续性、CPU定价权",
            },
            {
                "code": "MU",
                "status": "待确认",
                "risk_change": "利好：Q2营收238.6亿/+200%、Q3毛利指引81%、HBM卖到2026；利空：PE 24.5x、短期超买",
                "action": "待填入；超级周期成立，大幅浮盈建议部分止盈+移动止损",
                "trigger": "—",
                "invalidation": "HBM租赁价月度环比下降或DRAM现货大跌>10%",
                "watch": "HBM价格、产能释放、DRAM现货",
            },
            {
                "code": "NVDA",
                "status": "待确认",
                "risk_change": "利好：Q1营收820亿超预期、算力租赁再涨价；利空：应收384.66亿、营运资本-236.27亿",
                "action": "持有核心仓位不追高；成本<200设移动止损（高点回调10-15%）",
                "trigger": "价格在220-250区间持有",
                "invalidation": "跌破205且两天无法收复则减仓",
                "watch": "应收账款变化、AI云客户营收增速",
            },
            {
                "code": "SNDK",
                "status": "待确认",
                "risk_change": "利好：NAND纯玩+AI SSD需求；花旗目标2025；利空：TTM PE约48倍、超10年中位数136%",
                "action": "仅适合小仓位；>1250部分止盈，不宜重仓",
                "trigger": "SNDK>1250盈利区间部分止盈",
                "invalidation": "跌破1000且三天不收复则清仓",
                "watch": "NAND现货价、机构持仓、13F暴露度",
            },
        ],
        "scenarios": [
            {
                "name": "情景一：继续上涨",
                "probability": 0.25,
                "trigger": "5/26后NDX站稳29600、SMH>550；OpenAI提交S-1引发AI板块共振",
                "do": "持有现有仓位，不上调目标、不追高；NVDA达目标区间系统性止盈",
                "dont": "加杠杆、追高小票、追买SNDK",
            },
            {
                "name": "情景二：顶部震荡（基准）",
                "probability": 0.55,
                "trigger": "NDX在28800-29600震荡，SMH在520-550，量能萎缩；Mag7与其他股分化持续",
                "do": "持有核心（NVDA、INTC、MU），止损收紧8-10%，部分止盈SNDK，少量VIX call/put对冲",
                "dont": "加仓、新多头、做空Mag7",
            },
            {
                "name": "情景三：下跌或泡沫破裂初期",
                "probability": 0.20,
                "trigger": "NDX跌破28500三日不收复，SMH<500，VIX>25；OpenAI IPO定价<8000亿或推迟；云AI收入环比增速降>10%",
                "do": "系统性止盈MU和SNDK；NVDA/INTC更紧止损；买VIX call对冲",
                "dont": "抄底、扛单、不加对冲",
            },
        ],
        "actions": [
            {"idx": 1, "action": "持有（收紧止损）", "target": "NVDA", "reason": "业绩强但应收/营运资本恶化；算力租赁涨价支撑", "trigger": "220-250美元区间", "stop": "跌破205且两天不收复则减仓", "period": "1-2周"},
            {"idx": 2, "action": "持有（移动止损）", "target": "MU", "reason": "HBM售罄2026+毛利率Q3指引81%", "trigger": "MU>140且HBM价格坚挺", "stop": "HBM租赁价月环比下降或DRAM现货大跌>10%", "period": "2-4周"},
            {"idx": 3, "action": "部分止盈", "target": "SNDK", "reason": "TTM PE 48倍超历史中位数136%", "trigger": "SNDK>1250", "stop": "跌破1000且三天不收复清仓", "period": "1周内"},
            {"idx": 4, "action": "买put对冲", "target": "QQQ/SPY", "reason": "宽度坍塌+SOX超买+OpenAI IPO抽水风险", "trigger": "QQQ>535建仓", "stop": "QQQ>555且Mag7继续强势则对冲失效", "period": "4-6周"},
            {"idx": 5, "action": "等待", "target": "现金", "reason": "无明确确定性机会", "trigger": "—", "stop": "—", "period": "1-2周"},
            {"idx": 6, "action": "观察", "target": "OpenAI IPO", "reason": "中期最大流动性风险", "trigger": "正式S-1后科技股坚挺>3天则风险消化", "stop": "—", "period": "持续"},
            {"idx": 7, "action": "观察", "target": "AI云收入", "reason": "真实需求是泡沫持续核心条件", "trigger": "大型云厂AI收入环比增速<前两季50%则减仓", "stop": "—", "period": "持续"},
            {"idx": 8, "action": "减少观察", "target": "小票AI软件", "reason": "宽度坍塌小票风险大", "trigger": "IWM/NDX弱势持续>1周", "stop": "—", "period": "1-2周"},
        ],
        "watch_points": [
            {"idx": 1, "point": "OpenAI IPO", "detail": "是否提交S-1、估值是否1万亿+、承销定价区间", "stars": 5},
            {"idx": 2, "point": "Hyperscaler Capex指引", "detail": "是否有云厂下调Capex（如+50%降至+30%以下）", "stars": 5},
            {"idx": 3, "point": "NVIDIA应收账款", "detail": "应收与库存周度/月度变化", "stars": 5},
            {"idx": 4, "point": "GPU租赁价格", "detail": "Nebius/CoreWeave/AWS定价趋势", "stars": 4},
            {"idx": 5, "point": "AI云收入增速", "detail": "Azure/AWS/GCP AI收入（Q2财报7月下旬起）", "stars": 5},
            {"idx": 6, "point": "SOX趋势位", "detail": "支撑550-560，关键520", "stars": 5},
            {"idx": 7, "point": "NDX趋势位", "detail": "支撑28500，心理位28000", "stars": 5},
            {"idx": 8, "point": "VIX", "detail": "突破23连续3天>20对冲加仓；突破25系统性信号", "stars": 4},
            {"idx": 9, "point": "HY OAS", "detail": "快速走扩至4.0%以上预警", "stars": 4},
            {"idx": 10, "point": "SMH宽度", "detail": "较200周线从150%收窄至<80%", "stars": 4},
        ],
        "core_summary": "SPX八周连涨但动能衰减、Mag7独撑宽度坍塌。OpenAI IPO抽水预期落地，NVDA财报beat但应收恶化。泡沫29/70：短期12、中期12、长期5。策略：震荡偏防守，持有核心收紧止损，部分止盈SNDK，准备QQQ put对冲，紧盯OpenAI S-1与云AI收入边际。",
    },
    "markdown": "",
}


def main() -> None:
    items: list = []
    if HISTORY.is_file():
        items = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            items = []
    gid = NEW_REPORT["generated_at_utc"]
    items = [x for x in items if (x.get("generated_at_utc") or "") != gid]
    items.append(NEW_REPORT)
    HISTORY.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ok: {len(items)} reports in {HISTORY}")


if __name__ == "__main__":
    main()
