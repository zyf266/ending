"""生成 NVDA 同级完整 *_research_report.json（MRVL/MU/MSFT/NOK/RKLB/IBM）。"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent


def save(code: str, payload: dict) -> None:
    path = DATA / f"{code.lower()}_research_report.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", path.name, "sections", len(payload.get("sections", [])))


def _scenarios(bull, base, bear):
    return {
        "type": "scenarios",
        "items": [
            {
                "key": "bull",
                "label": "乐观情景",
                "probability": bull["p"],
                "subtitle": bull["sub"],
                "range_low": bull["lo"],
                "range_high": bull["hi"],
                "note": bull["note"],
            },
            {
                "key": "base",
                "label": "基准情景",
                "probability": base["p"],
                "subtitle": base["sub"],
                "range_low": base["lo"],
                "range_high": base["hi"],
                "note": base["note"],
            },
            {
                "key": "bear",
                "label": "悲观情景",
                "probability": bear["p"],
                "subtitle": bear["sub"],
                "range_low": bear["lo"],
                "range_high": bear["hi"],
                "note": bear["note"],
            },
        ],
    }


MRVL = {
    "code": "MRVL",
    "name": "Marvell",
    "tagline": "AI数据中心互联与自定义ASIC基础设施",
    "institution": "香港沐龙资产管理有限公司",
    "report_date": "2026-05-18",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：FY2026创纪录财报",
            "subtitle": "数据中心业务占比达74%，战略转型完成",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "全年营收", "value": "$81.95亿", "lines": ["YoY +42%", "创历史新高"]},
                        {"icon": "cash", "title": "Non-GAAP EPS", "value": "$2.84", "lines": ["YoY +81%", "利润大幅提升"]},
                        {"icon": "server", "title": "Q4 营收", "value": "$22.19亿", "lines": ["YoY +22%", "稳健增长"]},
                        {"icon": "calendar", "title": "Q4 Non-GAAP EPS", "value": "$0.80", "lines": ["超出市场预期"]},
                    ],
                },
                {
                    "type": "dual_footer",
                    "items": [
                        {
                            "icon": "target",
                            "title": "绝对核心引擎",
                            "text": "数据中心业务占比达74%，营收与利润双双创历史新高，确立AI基础设施供应商领先地位。",
                        },
                        {
                            "icon": "chip",
                            "title": "战略定位",
                            "text": "自定义ASIC、高带宽光学互联、以太网交换与DPU构成AI集群关键网络基石。",
                        },
                    ],
                },
            ],
        },
        {
            "id": "01b",
            "title": "基本面数据快照：估值锚点与同业参照",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chart", "title": "Forward P/E", "text": "约44-46x，处于历史较高水平，反映AI基础设施增长预期。"},
                        {"icon": "layers", "title": "P/S Ratio", "text": "约18-19x，溢价由数据中心+40%增长指引支撑。"},
                        {"icon": "trophy", "title": "NVIDIA战略合作", "text": "20亿美元战略合作强化AI基础设施地位，形成稳固利益共同体。"},
                        {"icon": "rocket", "title": "设计订单", "text": "已获超50个Hyperscaler自定义硅芯片设计订单，客户粘性强。"},
                        {"icon": "stack", "title": "FY2027展望", "text": "全年营收预计近$110亿，数据中心业务预计+40%爆发式增长。"},
                        {"icon": "network", "title": "稀缺性溢价", "text": "估值高于行业均值但低于AVGO，需业绩持续超预期以维持。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动：AI集群需求爆炸",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心产品/业务需求",
                            "items": [
                                {"icon": "chip", "title": "自定义ASIC", "text": "专为AI加速器(XPU)设计，精准满足Hyperscaler定制化算力需求。"},
                                {"icon": "network", "title": "高带宽光学互联", "text": "800G+ PAM4技术突破传统瓶颈，解决AI集群内部海量数据传输难题。"},
                                {"icon": "server", "title": "以太网交换 & DPU", "text": "构建大规模、高稳定性AI集群的关键网络基石组件。"},
                            ],
                        },
                        {
                            "title": "供给 vs. 需求",
                            "items": [
                                {"icon": "factory", "title": "需求确定性", "text": "AI基建是长期轻周期，Hyperscaler资本开支持续强劲。"},
                                {"icon": "chart", "title": "产能爬坡", "text": "超50个定制芯片项目出货量快速爬坡，产能利用率维持高位。"},
                                {"icon": "line", "title": "长期催化剂", "text": "FY2027数据中心+40%，FY2028接近+50%，高增长预期可持续兑现。"},
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "需求催化剂与市场份额",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chip", "title": "自定义硅放量", "text": "AI加速器定制芯片订单创纪录，设计胜出达历史新高。"},
                        {"icon": "globe", "title": "光学互联升级", "text": "800G+向更高速率演进，AI集群规模扩大驱动互联需求。"},
                        {"icon": "robot", "title": "Hyperscaler CapEx", "text": "美欧云巨头AI资本开支为需求核心驱动力。"},
                        {"icon": "rocket", "title": "Q1 FY2027指引", "text": "营收$24亿±5%，显著高于市场共识。"},
                        {"icon": "trophy", "title": "技术领先", "text": "高带宽SerDes与光学技术解决AI时代数据传输关键瓶颈。"},
                    ],
                }
            ],
        },
        {
            "id": "02c",
            "title": "竞争格局与护城河",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "vs Broadcom", "text": "Marvell更专注DCI与特定场景定制，业务纯度更高、细分赛道更灵活。"},
                        {"icon": "server", "title": "vs NVIDIA/AMD", "text": "侧重底层互联层，与GPU生态互补大于竞争，共同构建数据中心基础设施。"},
                        {"icon": "network", "title": "技术壁垒", "text": "高带宽SerDes与光学积累深厚，大规模部署验证可靠性与性能。"},
                        {"icon": "stack", "title": "客户粘性", "text": "50+Hyperscaler设计订单形成强粘性，切换成本高。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "区域/地缘与风险变量",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "中国市场敞口", "text": "收入占比约36-40%，主要源于传统网络与存储，是重要现金流基石。"},
                        {"icon": "chip", "title": "AI业务隔离", "text": "数据中心AI增长由美欧Hyperscaler驱动，受地缘直接冲击较小。"},
                        {"icon": "factory", "title": "供应链多元化", "text": "加速越南、马来西亚等地布局，分散中美脱钩与关税风险。"},
                        {"icon": "trend", "title": "综合判断", "text": "中国市场风险主要影响传统业务，核心AI增长驱动力影响有限，总体可控。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力与毛利率：定价权",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "Non-GAAP毛利率", "value": "59-60%", "lines": ["长期稳定区间"]},
                        {"icon": "layers", "title": "Q1 FY2027指引", "value": "58.25-59.25%", "lines": ["可预测性强"]},
                        {"icon": "trend", "title": "驱动因素", "value": "产品组合优化", "lines": ["高价值AI产品占比提升", "规模效应释放"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "管理层指引与情绪",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "calendar", "title": "Q1 FY2027指引", "text": "营收$24亿±5%；Non-GAAP EPS $0.79±$0.05，显著高于共识。"},
                        {"icon": "rocket", "title": "全年展望", "text": "FY2027营收近$110亿，数据中心+40%爆发式增长。"},
                        {"icon": "trophy", "title": "管理层语气", "text": "强调「AI需求强劲」「订单创纪录」「设计胜出历史新高」，信心十足。"},
                        {"icon": "chart", "title": "指引可信度", "text": "历史指引偏保守且多次超预期，市场可信度高。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值分析与目标价模型（12–18个月）",
            "blocks": [
                _scenarios(
                    {"p": "35%", "sub": "AI资本开支超预期", "lo": 240, "hi": 280, "note": "份额持续扩张、技术壁垒加深、重大合作公告"},
                    {"p": "45%", "sub": "中性预期", "lo": 180, "hi": 220, "note": "AI需求稳健增长，业务执行符合市场预期"},
                    {"p": "20%", "sub": "下行风险", "lo": 100, "hi": 130, "note": "AI投资放缓、竞争加剧、宏观衰退与地缘冲突"},
                ),
                {
                    "type": "p",
                    "text": "当前价约$177，Forward P/E约44-46x，估值已部分消化利好。向上空间仍合理但需警惕宏观波动，建议分批建仓。",
                },
            ],
        },
        {
            "id": "07",
            "title": "交易策略与仓位建议",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "买入/加仓", "text": "$150-$160为中长期理想切入点。"},
                        {"icon": "target", "title": "减仓/卖出", "text": "$200+可能已反映过度乐观，建议逐步获利了结。"},
                        {"icon": "line", "title": "严格止损", "text": "有效跌破$140-$150应果断止损离场。"},
                        {"icon": "layers", "title": "仓位控制", "text": "单一个股建议5%-8%，适合作为AI基础设施核心仓位。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业联动与综合情景",
            "blocks": [
                {
                    "type": "p",
                    "text": "AI基础设施建设（互联+自定义ASIC）是持续多年的超级周期。低利率与科技CapEx环境友好，但经济衰退或高利率可能短期延缓进度。MRVL与NVDA、AVGO及半导体景气度高度联动，建议置于AI基础设施组合框架内配置。",
                }
            ],
        },
    ],
    "conclusion": "Marvell在自定义ASIC与光学互联领域构建差异化壁垒，FY2027数据中心+40%指引强劲；但估值已反映乐观预期，建议回调至$150-$160分批买入，严格控制仓位，长期关注订单落地与业绩兑现。评级：持有/择机买入，信心65/100。",
}

MU = {
    "code": "MU",
    "name": "美光",
    "tagline": "AI超级周期下的内存与HBM核心受益者",
    "institution": "香港沐龙资产管理有限公司",
    "report_date": "2026-05-18",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：FY2026 Q2财报创纪录",
            "subtitle": "HBM驱动存储超级周期",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "季度总营收", "value": "$23.86B", "lines": ["QoQ +75%", "YoY +196%"]},
                        {"icon": "cash", "title": "Non-GAAP EPS", "value": "$12.20", "lines": ["远超市场预期"]},
                        {"icon": "shield", "title": "Non-GAAP毛利率", "value": "~74.9%", "lines": ["历史高位"]},
                        {"icon": "layers", "title": "DRAM / NAND", "value": "79% / 21%", "lines": ["HBM为核心驱动力"]},
                    ],
                },
                {
                    "type": "dual_footer",
                    "items": [
                        {"icon": "target", "title": "行业地位", "text": "全球三大内存制造商之一，深度绑定英伟达、AMD等AI巨头，是AI硬件浪潮核心受益者。"},
                        {"icon": "chip", "title": "股价背景", "text": "报告时点约$725，处于历史高位，业绩与估值双升，显著受益于AI半导体超级周期。"},
                    ],
                },
            ],
        },
        {
            "id": "01b",
            "title": "基本面数据快照：三巨头横向对比",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chart", "title": "Micron (MU)", "text": "营收增速QoQ +75%/YoY +196%，毛利率~75%，执行力与增速突出。"},
                        {"icon": "layers", "title": "SK Hynix", "text": "QoQ +60%/YoY +198%，运营利润率72%创新高，HBM利润率行业领先。"},
                        {"icon": "stack", "title": "Samsung", "text": "Memory业务创纪录，规模最大、业务多元化，供应链整合能力极强。"},
                        {"icon": "trophy", "title": "行业结论", "text": "三巨头均显著受益于AI/HBM超级周期，竞争格局稳固。"},
                        {"icon": "rocket", "title": "Q3指引", "text": "营收$33.5B±0.75B，毛利率~81%，EPS ~$19.15。"},
                        {"icon": "network", "title": "范式转变", "text": "管理层认为当前是AI驱动的行业范式转变，而非传统库存周期反弹。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动：HBM爆炸式增长",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心需求",
                            "items": [
                                {"icon": "chip", "title": "内存用量跃升", "text": "单台AI服务器HBM/高端DRAM搭载量为传统服务器数倍。"},
                                {"icon": "server", "title": "供需错配", "text": "HBM工艺复杂、良率挑战大，2026年产能基本售罄，长单锁定。"},
                                {"icon": "network", "title": "TAM扩张", "text": "HBM市场预计到2028年接近千亿美元规模。"},
                            ],
                        },
                        {
                            "title": "HBM份额格局",
                            "items": [
                                {"icon": "factory", "title": "SK Hynix领跑", "text": "早期技术布局与客户深度绑定，占据领先地位。"},
                                {"icon": "chart", "title": "Micron追赶", "text": "赢得NVIDIA平台设计订单后份额快速提升，潜力巨大。"},
                                {"icon": "line", "title": "Samsung加速", "text": "HBM4备受期待，全力追赶以实现份额突破。"},
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "需求催化剂与长期能见度",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chip", "title": "AI CapEx", "text": "超大规模数据中心AI资本开支驱动需求至2027年后。"},
                        {"icon": "globe", "title": "供给纪律", "text": "三寡头严格供给控制，支撑高利润防守。"},
                        {"icon": "robot", "title": "终端双轮", "text": "云厂商与终端侧双轮驱动内存消耗。"},
                        {"icon": "rocket", "title": "美股流动性", "text": "相比韩国同行，治理透明、流动性更佳。"},
                        {"icon": "trophy", "title": "估值吸引力", "text": "Forward PE处于个位数至低双位数，风险收益比佳。"},
                    ],
                }
            ],
        },
        {
            "id": "02c",
            "title": "竞争格局与护城河",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "三寡头格局", "text": "SK海力士、三星、美光瓜分HBM/高端DRAM市场，进入壁垒极高。"},
                        {"icon": "server", "title": "技术追赶", "text": "美光在NVIDIA生态订单验证技术实力，差距持续缩小。"},
                        {"icon": "network", "title": "定价权", "text": "供给紧张下三巨头毛利率均处历史峰值，定价权强劲。"},
                        {"icon": "stack", "title": "周期属性", "text": "虽AI需求结构性，传统半导体周期波动仍需警惕。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "区域/地缘与风险变量",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "中国敞口", "text": "中国收入占比约12%，AI全球化（美欧主导）有效缓解风险。"},
                        {"icon": "chip", "title": "制造布局", "text": "制造基地分散于美国、新加坡等地。"},
                        {"icon": "factory", "title": "地缘风险", "text": "中美脱钩、出口管制、关税及供应链中断为共同挑战。"},
                        {"icon": "trend", "title": "本土替代", "text": "中国本土内存产业替代进程推进，长期竞争格局生变。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力与毛利率：定价权",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "毛利率峰值", "value": "~75%", "lines": ["三巨头均处历史高位"]},
                        {"icon": "layers", "title": "Q3指引毛利率", "value": "~81%", "lines": ["继续创新高"]},
                        {"icon": "trend", "title": "防守逻辑", "value": "供给纪律+AI", "lines": ["结构性需求", "非传统周期反弹"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "管理层指引与情绪",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "calendar", "title": "Q3官方指引", "text": "营收$33.5B±0.75B，毛利率~81%，EPS ~$19.15，创历史新高。"},
                        {"icon": "rocket", "title": "结构性需求", "text": "管理层强调AI带来长期结构性需求，将持续多年。"},
                        {"icon": "trophy", "title": "行业共识", "text": "SK海力士与三星均给出强势指引，全行业迎来新增长纪元。"},
                        {"icon": "chart", "title": "市场预期", "text": "强劲指引推高市场期望，需关注Q3财报（约6月）兑现节奏。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值分析与目标价模型（12–18个月）",
            "blocks": [
                _scenarios(
                    {"p": "35%", "sub": "HBM份额升至25%+", "lo": 950, "hi": 1100, "note": "AI资本开支超预期，行业景气持续上行"},
                    {"p": "45%", "sub": "中性预期", "lo": 650, "hi": 780, "note": "需求稳健，产能利用率高位，利润率正常化"},
                    {"p": "20%", "sub": "下行风险", "lo": 350, "hi": 480, "note": "AI ROI受质疑、宏观衰退、资本开支缩减"},
                ),
                {"type": "p", "text": "当前约$725，Forward PE仍具吸引力，向上空间大于下行风险，但波动大，建议关注资本开支落地与库存周期。"},
            ],
        },
        {
            "id": "07",
            "title": "交易策略与仓位建议",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "加仓区域", "text": "$600-$650为强势回调后优质买点。"},
                        {"icon": "target", "title": "谨慎区域", "text": "$800+接近压力位，可部分获利了结。"},
                        {"icon": "line", "title": "止损纪律", "text": "有效跌破$550-$600坚决离场。"},
                        {"icon": "layers", "title": "仓位建议", "text": "核心AI内存仓位5%-10%，可搭配韩国半导体ETF分散风险。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业联动与综合情景",
            "blocks": [
                {
                    "type": "p",
                    "text": "半导体行业进入AI驱动超级周期，区别于传统库存周期。低利率与科技CapEx环境有利，但宏观衰退或高利率可能延缓节奏。MU与NVDA、MRVL及存储产业链高度联动，建议作为AI硬件主线核心配置。",
                }
            ],
        },
    ],
    "conclusion": "美光处于AI存储超级周期核心位置，HBM执行力与毛利率防守突出，Q3指引强劲。建议买入/持有作为核心AI内存仓位，回调至$600-$650加仓，严格止损。信心70/100。",
}

MSFT = {
    "code": "MSFT",
    "name": "微软",
    "tagline": "云+AI平台型企业，Azure与Copilot双引擎",
    "institution": "香港沐龙资产管理有限公司",
    "report_date": "2026-05-18",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：FY2026 Q3创纪录",
            "subtitle": "云+AI转型加速，利润率与现金流创新高",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "总营收", "value": "$828.86亿", "lines": ["YoY +18%", "大幅超预期"]},
                        {"icon": "cash", "title": "GAAP EPS", "value": "$4.27", "lines": ["YoY +23%"]},
                        {"icon": "cloud", "title": "Microsoft Cloud", "value": "$545亿", "lines": ["YoY +29%"]},
                        {"icon": "calendar", "title": "净收入", "value": "$317.78亿", "lines": ["YoY +23%"]},
                    ],
                },
                {
                    "type": "dual_footer",
                    "items": [
                        {"icon": "target", "title": "增长引擎", "text": "Azure同比增长+40%，Copilot与AI服务贡献显著增量，Cloud成为绝对核心。"},
                        {"icon": "chip", "title": "CapEx上调", "text": "全年资本支出指引上调至$1900亿，用于扩建AI基础设施与算力。"},
                    ],
                },
            ],
        },
        {
            "id": "01b",
            "title": "基本面数据快照：业务分部与财务健康",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "server", "title": "Intelligent Cloud", "text": "含Azure，主导增长引擎，企业级订阅持续强劲。"},
                        {"icon": "layers", "title": "Productivity & Business", "text": "Office 365、Dynamics、LinkedIn与Copilot订阅加速渗透。"},
                        {"icon": "stack", "title": "More Personal Computing", "text": "Windows、搜索、游戏受PC低迷拖累，增速放缓。"},
                        {"icon": "cash", "title": "现金极其充裕", "text": "自由现金流优异，支撑巨额CapEx与股东回报。"},
                        {"icon": "trend", "title": "ROE/ROIC", "text": "盈利能力持续高位，软件+云协同运营效率突出。"},
                        {"icon": "calendar", "title": "Q3 CapEx", "text": "当季$319亿，持续投入AI基础设施建设。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动：Azure与Copilot",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心需求",
                            "items": [
                                {"icon": "chip", "title": "AI基础设施", "text": "Azure AI服务与Copilot需求持续旺盛。"},
                                {"icon": "server", "title": "企业云迁移", "text": "存量客户上云进程加速，订阅模式现金流稳健。"},
                                {"icon": "network", "title": "数据+AI平台", "text": "一站式智能平台需求爆炸式增长。"},
                            ],
                        },
                        {
                            "title": "关键增长数据",
                            "items": [
                                {"icon": "factory", "title": "Azure增速", "text": "Q3 +40%，Q4指引维持39-40%（固定汇率）。"},
                                {"icon": "chart", "title": "AI ARR", "text": "已超$370亿，同比+123%，超预期。"},
                                {"icon": "line", "title": "容量紧张", "text": "数据中心HPC资源供不应求，CapEx大力扩张匹配需求。"},
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "需求催化剂与市场份额",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chip", "title": "Copilot渗透", "text": "企业级AI助手采用率超预期，带动高价值用户扩大。"},
                        {"icon": "globe", "title": "OpenAI合作", "text": "全栈AI能力从模型训练到应用部署。"},
                        {"icon": "robot", "title": "混合/主权云", "text": "满足跨国企业与政府数据本地化与合规需求。"},
                        {"icon": "rocket", "title": "云份额~28%", "text": "增速迅猛，依托365+Copilot深度整合建立粘性。"},
                        {"icon": "trophy", "title": "长期可持续性", "text": "根植于企业数字化转型与AI采用的长周期产业变革。"},
                    ],
                }
            ],
        },
        {
            "id": "02c",
            "title": "竞争格局与护城河",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "vs AWS (~31%)", "text": "AWS规模领先、生态成熟，但增速放缓。"},
                        {"icon": "server", "title": "vs Google Cloud (~13%)", "text": "体量最小但增速最快，纯AI创新优势。"},
                        {"icon": "network", "title": "生态锁定", "text": "深度绑定企业业务流程，迁移成本极高。"},
                        {"icon": "stack", "title": "企业市场", "text": "合规安全及政府/教育市场绝对优势。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "区域/地缘与风险变量",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "欧美主导", "text": "美国与欧洲贡献绝大部分收入，中国市场占比约5-8%。"},
                        {"icon": "chip", "title": "供应链调整", "text": "计划2026年起将大部分新产品制造移出中国，转向越南等地。"},
                        {"icon": "factory", "title": "全球监管", "text": "欧盟DMA/AI法案及数据本地化法规推高合规成本。"},
                        {"icon": "trend", "title": "综合判断", "text": "中国市场风险可控，最大不确定性来自全球监管升级。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力与毛利率：定价权",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "整体毛利率", "value": "~67.6%", "lines": ["历史高位"]},
                        {"icon": "layers", "title": "Cloud毛利率", "value": "稳健", "lines": ["规模效应提升"]},
                        {"icon": "trend", "title": "盈利防守", "value": "订阅+云", "lines": ["强现金流缓冲", "抗周期能力强"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "管理层指引与情绪",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "calendar", "title": "Q4营收指引", "text": "$867-878亿（+13-15%），延续稳健增长。"},
                        {"icon": "rocket", "title": "Azure指引", "text": "39-40%固定汇率增长，显著超共识。"},
                        {"icon": "trophy", "title": "管理层语气", "text": "Nadella强调「范式转变」，AI需求强劲且加速，容量紧张但执行出色。"},
                        {"icon": "chart", "title": "指引可信度", "text": "历史多次保守指引并最终超越，准确性极高。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值分析与目标价模型（12–18个月）",
            "blocks": [
                _scenarios(
                    {"p": "40%", "sub": "Copilot超预期", "lo": 580, "hi": 650, "note": "Azure高增长，利润率显著扩张"},
                    {"p": "45%", "sub": "中性预期", "lo": 480, "hi": 550, "note": "AI需求稳健，Azure ~35%+增长"},
                    {"p": "15%", "sub": "下行风险", "lo": 300, "hi": 360, "note": "AI ROI不及预期、IT支出疲软、监管冲击"},
                ),
                {"type": "p", "text": "当前约$422，Forward PE ~21-22x，风险收益比极具吸引力，向上空间显著大于下行风险。"},
            ],
        },
        {
            "id": "07",
            "title": "交易策略与仓位建议",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "加仓区域", "text": "$380-$400积极布局。"},
                        {"icon": "target", "title": "获利再平衡", "text": "$480+逐步止盈部分仓位。"},
                        {"icon": "line", "title": "严格止损", "text": "跌破$360-$380关键支撑离场。"},
                        {"icon": "layers", "title": "核心仓位", "text": "建议组合配置8%-15%，可搭配AWS/GOOG分散风险。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业联动与综合情景",
            "blocks": [
                {
                    "type": "p",
                    "text": "MSFT与全球AI资本开支、利率预期、企业IT支出及监管政策高度联动。建议作为科技核心长期仓位，通过长期持有平滑CapEx折旧与估值波动。",
                }
            ],
        },
    ],
    "conclusion": "微软AI驱动的长期增长逻辑稳固，Azure+Copilot双引擎强劲，管理层指引可信度高。建议买入/持有作为核心长期仓位，信心85/100。加仓$380-$400，止盈$550+分批减仓。",
}

NOK = {
    "code": "NOK",
    "name": "诺基亚",
    "tagline": "AI基础设施驱动的光网络转型",
    "institution": "香港沐龙资产管理有限公司",
    "report_date": "2026-05-18",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：Q1 2026复苏通道",
            "subtitle": "从5G低谷转向AI基础设施驱动",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "营收", "value": "€45亿", "lines": ["固定汇率 +4%"]},
                        {"icon": "shield", "title": "可比毛利率", "value": "45.5%", "lines": ["YoY +320bps"]},
                        {"icon": "trend", "title": "可比营业利润率", "value": "6.2%", "lines": ["YoY +200bps"]},
                        {"icon": "cash", "title": "自由现金流", "value": "€6.29亿", "lines": ["净现金 €38亿"]},
                    ],
                },
                {
                    "type": "dual_footer",
                    "items": [
                        {"icon": "target", "title": "Network Infrastructure", "text": "同比增长+6%，Optical Networks增长+20%，AI & Cloud净销售飙升+49%。"},
                        {"icon": "chip", "title": "订单动能", "text": "新增订单达€10亿，光网络业务势头强劲，CapEx €9-10亿支持扩张。"},
                    ],
                },
            ],
        },
        {
            "id": "01b",
            "title": "基本面数据快照：业务转型与财务健康",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "cash", "title": "净现金强劲", "text": "€38亿净现金，资本结构健康，抗风险能力强。"},
                        {"icon": "trend", "title": "盈利能力修复", "text": "毛利率与现金流显著改善，ROE/ROIC处于改善通道。"},
                        {"icon": "rocket", "title": "AI & Cloud", "text": "受云厂商资本开支驱动，净销售同比+49%。"},
                        {"icon": "stack", "title": "Infinera收购", "text": "显著提升AI数据中心互联市场战略定位，协同超预期。"},
                        {"icon": "network", "title": "Mobile Networks", "text": "表现平稳，降本增效保持业务韧性。"},
                        {"icon": "trophy", "title": "估值吸引力", "text": "Forward PE低双位数，PS/EV/EBITDA处于历史低位。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动：光网络与DCI",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心产品/业务",
                            "items": [
                                {"icon": "chip", "title": "全栈网络", "text": "5G/6G RAN、光网络传输、IP路由交换机及AI网络自动化。"},
                                {"icon": "server", "title": "AI/云需求", "text": "数据中心互联(DCI)需求激增，光网络设备供需紧张。"},
                                {"icon": "network", "title": "运营商投资", "text": "聚焦5G-Advanced及6G基础设施长期演进。"},
                            ],
                        },
                        {
                            "title": "长期催化剂",
                            "items": [
                                {"icon": "factory", "title": "光网络指引", "text": "2026年增长指引上调至18-20%。"},
                                {"icon": "chart", "title": "网络基建", "text": "全年增长指引上调至12-14%（前值6-8%）。"},
                                {"icon": "line", "title": "NVIDIA合作", "text": "深度合作开发AI-native原生网络架构，6G研究领先。"},
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "需求催化剂与订单能见度",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chip", "title": "云CapEx", "text": "超大规模云厂商资本开支驱动光网络订单。"},
                        {"icon": "globe", "title": "企业私有网", "text": "企业级私有无线网络方案成熟，差异化优势。"},
                        {"icon": "robot", "title": "Q2环比", "text": "管理层指引Q2环比增长5-9%。"},
                        {"icon": "rocket", "title": "专利组合", "text": "庞大专利构建技术壁垒，获欧美政府与运营商信任。"},
                        {"icon": "trophy", "title": "AI转型故事", "text": "逐步兑现有望带来估值扩张空间。"},
                    ],
                }
            ],
        },
        {
            "id": "02c",
            "title": "竞争格局与护城河",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "vs Ericsson", "text": "RAN份额领先但Optical/IP较弱；西方RAN双寡头格局。"},
                        {"icon": "server", "title": "vs Huawei", "text": "技术储备深厚但西方市场拓展受地缘限制。"},
                        {"icon": "network", "title": "vs Cisco/Arista", "text": "数据中心交换机统治力强，正向运营商边缘渗透。"},
                        {"icon": "stack", "title": "Nokia优势", "text": "光网络与IP路由技术领先，护城河中等坚固。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "区域/地缘与风险变量",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "核心市场", "text": "欧洲、北美为主导，AI/cloud与运营商业务高度集中。"},
                        {"icon": "chip", "title": "地缘风险", "text": "中美及欧中关系波动影响供应链与市场准入。"},
                        {"icon": "factory", "title": "应对策略", "text": "供应链多元化与西方市场本地化生产研发。"},
                        {"icon": "trend", "title": "综合判断", "text": "中国市场风险可控，但全球地缘不确定性仍需监控。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力与毛利率：定价权",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "可比毛利率", "value": "45.5%", "lines": ["YoY +320bps"]},
                        {"icon": "layers", "title": "驱动因素", "value": "产品结构优化", "lines": ["Infinera协同", "高价值Optical占比提升"]},
                        {"icon": "trend", "title": "外部压力", "value": "运营商CapEx", "lines": ["资本支出纪律带来压力"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "管理层指引与情绪",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "calendar", "title": "全年指引", "text": "可比营业利润€20-25亿；网络基建增长12-14%；光通信/IP增长18-20%。"},
                        {"icon": "rocket", "title": "语气积极", "text": "强调AI与云服务需求强劲，光通信是核心增长引擎。"},
                        {"icon": "trophy", "title": "低预期高兑现", "text": "Q1超预期后上调全年指引，投资者信誉度提升。"},
                        {"icon": "chart", "title": "市场预期", "text": "AI增长预期抬升，任何不及预期可能引发回调。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值分析与目标价模型（12–18个月）",
            "blocks": [
                _scenarios(
                    {"p": "35%", "sub": "Optical持续高增长", "lo": 18, "hi": 22, "note": "AI/cloud超预期，6G/AI-RAN里程碑落地"},
                    {"p": "45%", "sub": "中性预期", "lo": 13, "hi": 16, "note": "网络基建12-14%增速，毛利率稳定"},
                    {"p": "20%", "sub": "下行风险", "lo": 7, "hi": 10, "note": "运营商CapEx放缓、AI ROI不及预期、地缘冲击"},
                ),
                {"type": "p", "text": "当前约$13.95，估值具备吸引力，AI转型故事提供上行空间，但传统电信周期属性仍在。"},
            ],
        },
        {
            "id": "07",
            "title": "交易策略与仓位建议",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "加仓区域", "text": "$11.5-$12.5逢低吸纳。"},
                        {"icon": "target", "title": "止盈", "text": "$15+分批止盈，$17+大幅减仓。"},
                        {"icon": "line", "title": "止损", "text": "跌破$10-$11关键支撑离场。"},
                        {"icon": "layers", "title": "仓位", "text": "AI基础设施转型仓位4%-8%，可搭配爱立信分散风险。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业联动与综合情景",
            "blocks": [
                {
                    "type": "p",
                    "text": "诺基亚与全球电信CapEx、云厂商投资及地缘政策高度相关。光网络转型是核心叙事，适合中长期投资者在AI基础设施主题下配置，严格跟踪订单与毛利率边际变化。",
                }
            ],
        },
    ],
    "conclusion": "诺基亚正从5G低谷转向AI基础设施复苏，光网络转型提供上行空间，管理层指引上调增强信心。建议持有/择机买入，信心65/100，逢低$11.5-$12.5布局。",
}

RKLB = {
    "code": "RKLB",
    "name": "Rocket Lab",
    "tagline": "垂直整合的太空发射与卫星系统",
    "institution": "香港沐龙资产管理有限公司",
    "report_date": "2026-05-18",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：Q1 2026创纪录季度",
            "subtitle": "首次突破$200M营收大关",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "总营收", "value": "$200.3M", "lines": ["YoY +63.5%", "QoQ +11.5%"]},
                        {"icon": "cash", "title": "GAAP EPS", "value": "-$0.07", "lines": ["优于预期 -$0.08"]},
                        {"icon": "shield", "title": "毛利率", "value": "38.2%", "lines": ["创历史新高"]},
                        {"icon": "calendar", "title": "Adj. EBITDA", "value": "-$11.75M", "lines": ["同比改善60.8%"]},
                    ],
                },
                {
                    "type": "dual_footer",
                    "items": [
                        {"icon": "target", "title": "Space Systems", "text": "收入$136.7M（~68%），YoY +57.2%，卫星平台与组件为增长主力。"},
                        {"icon": "chip", "title": "Launch Services", "text": "收入$63.7M（~32%），YoY +78.9%，Electron火箭高可靠性贡献稳定营收。"},
                    ],
                },
            ],
        },
        {
            "id": "01b",
            "title": "基本面数据快照：流动性与订单储备",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "cash", "title": "总流动性", "text": "超$20亿（含股权发行后），资金储备充裕。"},
                        {"icon": "trend", "title": "订单储备", "text": "Backlog $2.2B同比大幅增长，收入可见度极高。"},
                        {"icon": "rocket", "title": "Neutron催化剂", "text": "中运力火箭13,000kg+至LEO，目标2026 Q4首飞。"},
                        {"icon": "stack", "title": "Electron验证", "text": "50+次成功发射，小运力市场绝对领先。"},
                        {"icon": "network", "title": "运营现金流", "text": "经营性现金流持续改善，造血能力增强。"},
                        {"icon": "calendar", "title": "FCF阶段", "text": "自由现金流短期为负，主要因Neutron战略研发投入。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动：国防与商业星座",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心产品/业务",
                            "items": [
                                {"icon": "chip", "title": "Electron火箭", "text": "小运力市场领先者，高频率发射能力是现金流支柱。"},
                                {"icon": "server", "title": "Space Systems", "text": "卫星总线与组件制造，高价值高毛利，深度绑定商业客户。"},
                                {"icon": "network", "title": "Neutron火箭", "text": "可回收中运力火箭，运力超13吨至LEO，将打破市场格局。"},
                            ],
                        },
                        {
                            "title": "核心需求",
                            "items": [
                                {"icon": "factory", "title": "国防政府", "text": "SDA、高超音速武器及天基拦截器等项目需求强劲。"},
                                {"icon": "chart", "title": "商业星座", "text": "全球卫星星座部署浪潮，制造与发射需求指数级增长。"},
                                {"icon": "line", "title": "供需缺口", "text": "小运力长期供不应求，Neutron精准切入中运力空白。"},
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "需求催化剂与TAM扩张",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chip", "title": "Neutron首飞", "text": "2026 Q4最大增长事件，TAM扩大一个数量级。"},
                        {"icon": "globe", "title": "垂直整合", "text": "制造-发射-运营全链条，提升粘性与利润率。"},
                        {"icon": "robot", "title": "M&A布局", "text": "Mynaric、Motiv等收购强化多元化与国防能力。"},
                        {"icon": "rocket", "title": "Q2指引", "text": "营收$225-240M，中点大幅高于共识。"},
                        {"icon": "trophy", "title": "政府信任", "text": "美及盟国政府高度信任，独家专利技术壁垒。"},
                    ],
                }
            ],
        },
        {
            "id": "02c",
            "title": "竞争格局与护城河",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "vs SpaceX", "text": "SpaceX绝对主导，RKLB专注差异化竞争避开正面交锋。"},
                        {"icon": "server", "title": "vs Firefly/Relativity", "text": "中小运力竞争者规模与成熟度仍落后。"},
                        {"icon": "network", "title": "唯一上市", "text": "垂直整合纯太空上市公司，Electron+Space Systems多元化。"},
                        {"icon": "stack", "title": "核心风险", "text": "Neutron能否按时首飞是决定份额与估值的关键变量。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "区域/地缘与风险变量",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "美欧为主", "text": "业务高度集中于美国、欧洲及核心盟国，结构稳定。"},
                        {"icon": "chip", "title": "双基地", "text": "美国与新西兰制造基地分散单一区域风险。"},
                        {"icon": "factory", "title": "供应链", "text": "部分关键电子组件亚洲暴露，需警惕断供与物流延误。"},
                        {"icon": "trend", "title": "国防预算", "text": "美国国防预算年度波动是最大不确定性变量。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力与毛利率：定价权",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "Q1毛利率", "value": "38.2%", "lines": ["GAAP创纪录"]},
                        {"icon": "layers", "title": "Q2指引", "value": "33-35% GAAP", "lines": ["Non-GAAP 38-40%"]},
                        {"icon": "trend", "title": "驱动因素", "value": "产品组合", "lines": ["Space Systems占比提升", "规模效应"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "管理层指引与情绪",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "calendar", "title": "Q2指引", "text": "营收$225-240M；毛利率GAAP 33-35%；EBITDA亏损继续收窄。"},
                        {"icon": "rocket", "title": "高度自信", "text": "强调「纪录季度」「强劲执行」「强大需求尾风」。"},
                        {"icon": "trophy", "title": "保守超越", "text": "历史指引偏保守且多次超预期，信誉极高。"},
                        {"icon": "chart", "title": "市场预期", "text": "Neutron执行预期处于高位，微小延误可能引发波动。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值分析与目标价模型（12–18个月）",
            "blocks": [
                _scenarios(
                    {"p": "35%", "sub": "Neutron成功首飞", "lo": 180, "hi": 220, "note": "快速量产、大量合同、margin扩张"},
                    {"p": "45%", "sub": "中性预期", "lo": 110, "hi": 140, "note": "Neutron按计划推进，Backlog正常转化"},
                    {"p": "20%", "sub": "下行风险", "lo": 50, "hi": 80, "note": "Neutron延误/失败、发射事故、国防预算削减"},
                ),
                {"type": "p", "text": "当前约$120-125，高Beta成长股，高PS支撑于Backlog与增速，执行风险高需密切跟踪Neutron节点。"},
            ],
        },
        {
            "id": "07",
            "title": "交易策略与仓位建议",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "加仓区域", "text": "$100-$110低估区间。"},
                        {"icon": "target", "title": "谨慎获利", "text": "$140+技术压力位，$160+分批减仓。"},
                        {"icon": "line", "title": "止损", "text": "$90-$100严格执行。"},
                        {"icon": "layers", "title": "仓位", "text": "高波动成长股3%-7%，仅适合高风险承受力投资者。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业联动与综合情景",
            "blocks": [
                {
                    "type": "p",
                    "text": "Rocket Lab与国防预算、商业航天景气度及Neutron项目进度高度绑定。行业处于技术突破前夜，政策红利持续，但地缘与供应链扰动可能带来高波动。",
                }
            ],
        },
    ],
    "conclusion": "Rocket Lab订单储备$2.2B、毛利持续改善，Neutron首飞将打开巨大市场空间。建议择机买入/持有作为高风险高回报成长仓位，信心60/100，密切跟踪Neutron关键节点。",
}

IBM = {
    "code": "IBM",
    "name": "IBM",
    "tagline": "关键基础设施软件与混合云防守型价值股",
    "institution": "香港沐龙资产管理有限公司",
    "report_date": "2026-06-02",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：2026 Q1全面超预期",
            "subtitle": "软件业务巩固增长引擎地位",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "总营收", "value": "$159.2亿", "lines": ["YoY +9%", "超$156.2亿预期"]},
                        {"icon": "cash", "title": "Non-GAAP EPS", "value": "$1.91", "lines": ["YoY +19%"]},
                        {"icon": "layers", "title": "软件部门", "value": "$70.52亿", "lines": ["YoY +11%", "占比44.3%"]},
                        {"icon": "server", "title": "基础设施", "value": "$33.26亿", "lines": ["YoY +15%", "大型机+51%脉冲"]},
                    ],
                },
                {
                    "type": "dual_footer",
                    "items": [
                        {"icon": "target", "title": "转型成效", "text": "软件营收占比从约35%升至44.3%，完成向高附加值软件与服务战略转型。"},
                        {"icon": "chip", "title": "自由现金流", "text": "Q1 FCF $22亿极强开局，咨询业务$52.72亿（YoY +4%）提供稳健防御。"},
                    ],
                },
            ],
        },
        {
            "id": "01b",
            "title": "基本面数据快照：资产负债表与股东回报",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "cash", "title": "现金储备", "text": "现金及可售证券$118亿，总债务$664亿，杠杆率<3.0x。"},
                        {"icon": "trend", "title": "ROE/ROIC", "text": "ROE ~49%，ROIC ~25-30%，资本回报强劲。"},
                        {"icon": "stack", "title": "高股息防御", "text": "股息率2.6-2.7%，十年稳步增长，科技巨头中防御核心。"},
                        {"icon": "rocket", "title": "战略并购", "text": "2025年完成含HashiCorp在内10笔收购，补强DevOps与云管理。"},
                        {"icon": "network", "title": "RPO", "text": "剩余履约义务$680亿，为未来1-2年收入提供高度可见性。"},
                        {"icon": "trophy", "title": "评级展望", "text": "信用评级展望稳定，财务结构可控。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动：软件与AI变现",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心业务",
                            "items": [
                                {"icon": "chip", "title": "软件增长", "text": "连续多季度10%+增长，2026全年指引10%以上，订阅与RPO占比提升。"},
                                {"icon": "server", "title": "咨询韧性", "text": "YoY +4%，重心转向AI生成式服务，抗周期能力强。"},
                                {"icon": "network", "title": "基础设施脉冲", "text": "Q1 +15%源于大型机+51%，全年指引仍为低个位数跌幅。"},
                            ],
                        },
                        {
                            "title": "AI与量子",
                            "items": [
                                {"icon": "factory", "title": "AI变现", "text": "AI相关软件与服务收入同比+40%，技术优势转化为商业价值。"},
                                {"icon": "chart", "title": "政府背书", "text": "获美国联邦政府$10亿承诺支持量子晶圆厂建设。"},
                                {"icon": "line", "title": "量子投入", "text": "未来五年投入超$100亿强化量子计算研发制造。"},
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "需求催化剂与双轮驱动",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chip", "title": "混合云", "text": "深耕企业级复杂环境自动化基建软件。"},
                        {"icon": "globe", "title": "AI治理需求", "text": "AI规模化应用催生自动化运维与可观测性软件需求。"},
                        {"icon": "robot", "title": "合规行业", "text": "金融、政府、国防领域高准入壁垒。"},
                        {"icon": "rocket", "title": "短期叙事", "text": "AI变现稳住基本盘。"},
                        {"icon": "trophy", "title": "长期叙事", "text": "量子计算打开第二增长曲线。"},
                    ],
                }
            ],
        },
        {
            "id": "02c",
            "title": "竞争格局与护城河",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "vs MSFT/ORCL", "text": "不与公有云巨头争锋，深耕混合云管理与大型机生态蓝海。"},
                        {"icon": "server", "title": "迁移成本", "text": "基建软件深度嵌入业务流程，替换周期动辄数年。"},
                        {"icon": "network", "title": "监管护城河", "text": "强监管行业解决方案通过严苛认证，新进入者难以短期复制。"},
                        {"icon": "stack", "title": "巴克莱观点", "text": "AI发展增厚基建软件长期价值，而非颠覆核心业务。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "区域/地缘与风险变量",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "估值透支", "text": "六周内估值重估，前瞻PE超越微软，为首要风险。"},
                        {"icon": "chip", "title": "大型机回落", "text": "Q1脉冲难持续，下半年基础设施业务或承压。"},
                        {"icon": "factory", "title": "AI订单节奏", "text": "企业客户或缩减AI预算，增速可能放缓。"},
                        {"icon": "trend", "title": "内部人减持", "text": "CFO在$300-318区间减持3000股，信号意义需关注。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力与毛利率：定价权",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "Non-GAAP毛利率", "value": ">60%", "lines": ["Q1站稳60%上方"]},
                        {"icon": "layers", "title": "部门改善", "value": "双升", "lines": ["基础设施+720bps", "软件+60bps"]},
                        {"icon": "trend", "title": "生产力节省", "value": "$45亿", "lines": ["自2023年以来累计"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "管理层指引与情绪",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "calendar", "title": "全年指引", "text": "固定汇率营收+5%以上；软件+10%以上；FCF ~$157亿。"},
                        {"icon": "rocket", "title": "审慎风格", "text": "CFO重申全年展望「现阶段审慎为宜」，未激进上调。"},
                        {"icon": "trophy", "title": "CEO表态", "text": "Krishna称Q1开局「强劲」，预期全年增长超5%。"},
                        {"icon": "chart", "title": "市场反应", "text": "财报后盘前跌近7%，因市场期待更激进指引上调。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值分析与目标价模型（12–18个月）",
            "blocks": [
                _scenarios(
                    {"p": "15%", "sub": "AI持续超预期", "lo": 400, "hi": 449, "note": "软件增长强劲，降息周期流动性宽松"},
                    {"p": "60%", "sub": "中性预期", "lo": 325, "hi": 355, "note": "全年营收5-6%稳健增长，符合指引"},
                    {"p": "25%", "sub": "下行风险", "lo": 240, "hi": 280, "note": "AI增速放缓、大型机回落、宏观下行"},
                ),
                {"type": "p", "text": "当前约$309，前瞻PE ~26-27x，13年来首次超越微软，估值合理偏高，追高盈亏比弱化。"},
            ],
        },
        {
            "id": "07",
            "title": "交易策略与仓位建议",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "观望为主", "text": "当前$309不宜追高，已持有可继续持有。"},
                        {"icon": "target", "title": "建仓区间", "text": "$280-$295小仓位试错；$260-$280稳健加仓。"},
                        {"icon": "line", "title": "止盈", "text": "$355-$375止盈50%仓位。"},
                        {"icon": "layers", "title": "仓位", "text": "平衡型2-4%，保守型1-2%以股息为核心。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业联动与综合情景",
            "blocks": [
                {
                    "type": "p",
                    "text": "IBM兼具高股息防守与AI/量子主题弹性。关注2026年7月Q2财报（软件增速与大型机订单）、10月Q3（AI收入增速）及量子晶圆厂产能里程碑。短期更多由AI叙事驱动，需警惕情绪退潮波动。",
                }
            ],
        },
    ],
    "conclusion": "IBM软件转型与AI变现已验证阶段性成果，高股息提供安全边际；但六周内估值快速重估已超越微软，当前$309建议持有观望、等待$280-$295回调再布局。评级C，信心中等偏低。",
}

if __name__ == "__main__":
    for code, payload in [
        ("MRVL", MRVL),
        ("MU", MU),
        ("MSFT", MSFT),
        ("NOK", NOK),
        ("RKLB", RKLB),
        ("IBM", IBM),
    ]:
        save(code, payload)
