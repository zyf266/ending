"""一次性生成 MRVL/MU/MSFT/NOK/RKLB/IBM 研究卡片与研报 JSON。"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent

SPECS = [
    {
        "code": "MRVL",
        "card": {
            "code": "MRVL",
            "name": "Marvell",
            "tagline": "AI数据中心互联与自定义ASIC基础设施",
            "institution": "香港沐龙资产管理有限公司",
            "report_date": "2026-05-18",
            "quote_symbol": "MRVL",
            "scenarios": [
                {"key": "bull", "label": "乐观情景", "probability": "35%", "subtitle": "AI资本开支超预期", "range_low": 240, "range_high": 280, "note": "PDF：$240-$280"},
                {"key": "base", "label": "基准情景", "probability": "45%", "subtitle": "需求稳健、执行正常", "range_low": 180, "range_high": 220, "note": "PDF：$180-$220"},
                {"key": "bear", "label": "悲观情景", "probability": "20%", "subtitle": "AI投资放缓/竞争加剧", "range_low": 100, "range_high": 130, "note": "PDF：$100-$130"},
            ],
            "highlights": [
                "FY2026 全年营收 $81.95亿（YoY +42%），数据中心业务占比 74%",
                "Non-GAAP EPS $2.84（YoY +81%），Q1 FY2027 指引营收 $24亿 ±5%",
                "自定义ASIC + 800G+ 光学互联 + 以太网交换/DPU 构成 AI 集群基础设施",
                "与 NVIDIA 20亿美元战略合作，已获超 50 个 Hyperscaler 设计订单",
                "核心风险：估值偏高、Broadcom 竞争、中国市场传统业务敞口",
            ],
            "pdf_path": "Marvell (MRVL) 美股分析报告.pdf",
        },
        "report": {
            "sections": [
                {
                    "id": "01",
                    "title": "基本面数据快照",
                    "subtitle": "FY2026 创纪录财报（PDF 第 3 页）",
                    "blocks": [
                        {
                            "type": "stat_cards",
                            "layout": "4",
                            "items": [
                                {"icon": "chart", "title": "全年营收", "value": "$81.95亿", "lines": ["YoY +42%", "创历史新高"]},
                                {"icon": "cash", "title": "Non-GAAP EPS", "value": "$2.84", "lines": ["YoY +81%"]},
                                {"icon": "trend", "title": "Q4 营收", "value": "$22.19亿", "lines": ["YoY +22%"]},
                                {"icon": "bolt", "title": "Q4 Non-GAAP EPS", "value": "$0.80", "lines": ["超市场预期"]},
                            ],
                        },
                        {
                            "type": "bullets",
                            "title": "结构性要点",
                            "items": [
                                "战略转型完成：数据中心业务占比达 74%，成为绝对增长引擎。",
                                "AI 基础设施供应商地位确立，营收与利润双双创历史新高。",
                            ],
                        },
                    ],
                },
                {
                    "id": "02",
                    "title": "需求端与增长驱动",
                    "subtitle": "AI 集群需求与竞争格局（PDF 第 4-6 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "自定义 ASIC：专为 AI 加速器(XPU) 设计，满足 Hyperscaler 定制化算力需求。",
                                "高带宽光学互联：800G+ PAM4 技术解决 AI 集群内部海量数据传输瓶颈。",
                                "以太网交换 & DPU：构建大规模、高稳定性 AI 集群的关键网络基石。",
                                "FY2027 数据中心营收预计 +40%，FY2028 接近 +50%。",
                            ],
                        },
                        {
                            "type": "bullets",
                            "title": "竞争与护城河",
                            "items": [
                                "vs Broadcom：Marvell 更专注 DCI 与特定场景定制，业务纯度更高。",
                                "vs NVIDIA/AMD：侧重底层互联层，与 GPU 生态互补大于竞争。",
                                "技术壁垒：高带宽 SerDes 与光学技术积累深厚，客户粘性强。",
                            ],
                        },
                    ],
                },
                {
                    "id": "06",
                    "title": "估值与三档目标价模型",
                    "subtitle": "当前价约 $177（PDF 第 10-11 页）",
                    "blocks": [
                        {
                            "type": "scenario_cards",
                            "items": [
                                {"key": "bull", "label": "乐观情景", "probability": "35%", "range": "$240–$280", "text": "AI资本开支超预期，份额持续扩张。"},
                                {"key": "base", "label": "基准情景", "probability": "45%", "range": "$180–$220", "text": "AI需求稳健增长，业务执行符合预期。"},
                                {"key": "bear", "label": "悲观情景", "probability": "20%", "range": "$100–$130", "text": "AI投资放缓、竞争加剧、利润率下滑。"},
                            ],
                        }
                    ],
                },
                {
                    "id": "09",
                    "title": "操作建议与仓位管理",
                    "subtitle": "持有 / 择机买入（PDF 第 12-14 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "买入/加仓区域：$150-$160；减仓区域：$200+；止损：$140-$150。",
                                "单一个股仓位建议 5%-8%，适合作为 AI 基础设施核心仓位。",
                                "评级：持有/择机买入，信心 65/100。",
                            ],
                        }
                    ],
                },
            ],
            "conclusion": "Marvell 在自定义 ASIC 与光学互联领域构建差异化壁垒，FY2027 数据中心 +40% 指引强劲；但估值已反映乐观预期，建议回调分批布局并控制仓位。",
        },
    },
    {
        "code": "MU",
        "card": {
            "code": "MU",
            "name": "美光",
            "tagline": "AI超级周期下的内存与HBM核心受益者",
            "institution": "香港沐龙资产管理有限公司",
            "report_date": "2026-05-18",
            "quote_symbol": "MU",
            "scenarios": [
                {"key": "bull", "label": "乐观情景", "probability": "35%", "subtitle": "HBM份额升至25%+", "range_low": 950, "range_high": 1100, "note": "PDF：$950-$1100"},
                {"key": "base", "label": "基准情景", "probability": "45%", "subtitle": "需求稳健、产能高位", "range_low": 650, "range_high": 780, "note": "PDF：$650-$780"},
                {"key": "bear", "label": "悲观情景", "probability": "20%", "subtitle": "AI资本开支缩减", "range_low": 350, "range_high": 480, "note": "PDF：$350-$480"},
            ],
            "highlights": [
                "FY2026 Q2 营收 $23.86B（QoQ +75% / YoY +196%）",
                "Non-GAAP EPS $12.20，Non-GAAP 毛利率 ~74.9% 处于历史高位",
                "DRAM $18.8B（79%）+ NAND $5.0B（21%），HBM 为核心增长引擎",
                "Q3 指引营收 $33.5B±0.75B，毛利率 ~81%，EPS ~$19.15",
                "核心风险：周期反转、地缘摩擦、三星/SK海力士竞争",
            ],
            "pdf_path": "Micron (MU) 分析报告.pdf",
        },
        "report": {
            "sections": [
                {
                    "id": "01",
                    "title": "核心基本面快照",
                    "subtitle": "MU FY2026 Q2 财报（PDF 第 3-4 页）",
                    "blocks": [
                        {
                            "type": "stat_cards",
                            "layout": "4",
                            "items": [
                                {"icon": "chart", "title": "季度营收", "value": "$23.86B", "lines": ["QoQ +75%", "YoY +196%"]},
                                {"icon": "cash", "title": "Non-GAAP EPS", "value": "$12.20", "lines": ["远超预期"]},
                                {"icon": "shield", "title": "Non-GAAP 毛利率", "value": "~74.9%", "lines": ["历史高位"]},
                                {"icon": "layers", "title": "DRAM / NAND", "value": "79% / 21%", "lines": ["HBM 驱动"]},
                            ],
                        }
                    ],
                },
                {
                    "id": "03",
                    "title": "增长驱动：AI与HBM",
                    "subtitle": "内存用量倍数级跃升（PDF 第 5-6 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "单台 AI 服务器内存搭载量为传统服务器数倍，HBM/高端 DRAM 需求爆炸式增长。",
                                "2026 年产能基本售罄，长单锁定，需求由超大规模数据中心 AI 资本开支驱动。",
                                "HBM TAM 预计到 2028 年接近千亿美元规模。",
                                "Micron 赢得 NVIDIA 平台设计订单后份额快速提升，正在缩小与 SK Hynix 差距。",
                            ],
                        }
                    ],
                },
                {
                    "id": "06",
                    "title": "估值与三档目标价模型",
                    "subtitle": "当前价约 $725（PDF 第 9-10 页）",
                    "blocks": [
                        {
                            "type": "scenario_cards",
                            "items": [
                                {"key": "bull", "label": "乐观情景", "probability": "35%", "range": "$950–$1100", "text": "AI资本开支超预期，HBM份额升至25%+。"},
                                {"key": "base", "label": "基准情景", "probability": "45%", "range": "$650–$780", "text": "需求稳健，产能利用率维持高位。"},
                                {"key": "bear", "label": "悲观情景", "probability": "20%", "range": "$350–$480", "text": "AI ROI受质疑、宏观衰退冲击需求。"},
                            ],
                        }
                    ],
                },
                {
                    "id": "09",
                    "title": "操作建议",
                    "subtitle": "买入/持有（PDF 第 11-12 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "加仓区域：$600-$650；谨慎区域：$800+；止损：$550-$600。",
                                "单一个股仓位 5%-10%，可作为核心 AI 内存仓位。",
                                "评级：买入/持有，信心 70/100。",
                            ],
                        }
                    ],
                },
            ],
            "conclusion": "美光处于 AI 驱动的存储超级周期，HBM 执行力与毛利率防守能力突出；估值已部分反映乐观预期，建议关注 Q3 财报与资本开支落地节奏，回调布局更优。",
        },
    },
    {
        "code": "MSFT",
        "card": {
            "code": "MSFT",
            "name": "微软",
            "tagline": "云+AI平台型企业，Azure与Copilot双引擎",
            "institution": "香港沐龙资产管理有限公司",
            "report_date": "2026-05-18",
            "quote_symbol": "MSFT",
            "scenarios": [
                {"key": "bull", "label": "乐观情景", "probability": "40%", "subtitle": "Copilot超预期渗透", "range_low": 580, "range_high": 650, "note": "PDF：$580-$650"},
                {"key": "base", "label": "基准情景", "probability": "45%", "subtitle": "Azure维持35%+增长", "range_low": 480, "range_high": 550, "note": "PDF：$480-$550"},
                {"key": "bear", "label": "悲观情景", "probability": "15%", "subtitle": "AI ROI不及预期", "range_low": 300, "range_high": 360, "note": "PDF：$300-$360"},
            ],
            "highlights": [
                "FY2026 Q3 营收 $828.86亿（YoY +18%），GAAP EPS $4.27（YoY +23%）",
                "Microsoft Cloud $545亿（YoY +29%），Azure 同比增长 +40%",
                "AI 业务 ARR 超 $370亿（YoY +123%），Copilot 订阅加速渗透",
                "全年 CapEx 指引上调至 $1900亿，用于 AI 基础设施扩建",
                "核心风险：高估值敏感性、CapEx 压力、地缘/监管与云竞争",
            ],
            "pdf_path": "MSFT 美股分析报告.pdf",
        },
        "report": {
            "sections": [
                {
                    "id": "01",
                    "title": "基本面数据快照",
                    "subtitle": "FY2026 Q3 核心指标（PDF 第 3 页）",
                    "blocks": [
                        {
                            "type": "stat_cards",
                            "layout": "4",
                            "items": [
                                {"icon": "chart", "title": "总营收", "value": "$828.86亿", "lines": ["YoY +18%"]},
                                {"icon": "cash", "title": "GAAP EPS", "value": "$4.27", "lines": ["YoY +23%"]},
                                {"icon": "cloud", "title": "Microsoft Cloud", "value": "$545亿", "lines": ["YoY +29%"]},
                                {"icon": "bolt", "title": "Azure 增长", "value": "+40%", "lines": ["核心驱动力"]},
                            ],
                        }
                    ],
                },
                {
                    "id": "02",
                    "title": "需求端与竞争格局",
                    "subtitle": "云三强格局与护城河（PDF 第 4-5 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "Azure Q3 +40%，Q4 指引维持 39-40%（固定汇率）。",
                                "AI 业务 ARR 超 $370亿，同比 +123%，Copilot 采用率超预期。",
                                "AWS ~31% 份额 vs Azure ~28% vs Google Cloud ~13%。",
                                "护城河：生态锁定、全栈 AI 能力（OpenAI 合作）、混合/主权云布局。",
                            ],
                        }
                    ],
                },
                {
                    "id": "06",
                    "title": "估值与三档目标价模型",
                    "subtitle": "当前价约 $422（PDF 第 8 页）",
                    "blocks": [
                        {
                            "type": "scenario_cards",
                            "items": [
                                {"key": "bull", "label": "乐观情景", "probability": "40%", "range": "$580–$650", "text": "AI/Copilot超预期，Azure高增长，利润率扩张。"},
                                {"key": "base", "label": "基准情景", "probability": "45%", "range": "$480–$550", "text": "AI需求稳健释放，Azure ~35%+增长。"},
                                {"key": "bear", "label": "悲观情景", "probability": "15%", "range": "$300–$360", "text": "AI ROI不及预期、IT支出疲软、宏观衰退。"},
                            ],
                        }
                    ],
                },
                {
                    "id": "09",
                    "title": "操作建议",
                    "subtitle": "买入/持有核心长期仓位（PDF 第 9 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "加仓区域：$380-$400；获利再平衡：$480+；止损：$360-$380。",
                                "核心仓位建议 8%-15%，信心 85/100。",
                            ],
                        }
                    ],
                },
            ],
            "conclusion": "微软 AI 驱动的长期增长逻辑稳固，Azure+Copilot 双引擎强劲，管理层指引可信度高；当前价位风险收益比具吸引力，适合作为核心长期仓位持有。",
        },
    },
    {
        "code": "NOK",
        "card": {
            "code": "NOK",
            "name": "诺基亚",
            "tagline": "AI基础设施驱动的光网络转型",
            "institution": "香港沐龙资产管理有限公司",
            "report_date": "2026-05-18",
            "quote_symbol": "NOK",
            "scenarios": [
                {"key": "bull", "label": "乐观情景", "probability": "35%", "subtitle": "Optical持续高增长", "range_low": 18, "range_high": 22, "note": "PDF：$18-$22"},
                {"key": "base", "label": "基准情景", "probability": "45%", "subtitle": "网络基建12-14%增长", "range_low": 13, "range_high": 16, "note": "PDF：$13-$16"},
                {"key": "bear", "label": "悲观情景", "probability": "20%", "subtitle": "运营商CapEx放缓", "range_low": 7, "range_high": 10, "note": "PDF：$7-$10"},
            ],
            "highlights": [
                "Q1 2026 营收 €45亿（固定汇率 +4%），可比毛利率 45.5%（YoY +320bps）",
                "Network Infrastructure +6%，AI & Cloud 净销售飙升 +49%",
                "光通信/IP 增长指引上调至 18-20%，新增订单 €10亿",
                "净现金 €38亿，CapEx €9-10亿 重点支持 Optical 扩张",
                "核心风险：传统电信周期、地缘政策、AI转型执行不确定性",
            ],
            "pdf_path": "Nokia 美股分析报告.pdf",
        },
        "report": {
            "sections": [
                {
                    "id": "01",
                    "title": "基本面数据快照",
                    "subtitle": "Q1 2026 核心指标（PDF 第 3 页）",
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
                        }
                    ],
                },
                {
                    "id": "02",
                    "title": "需求端与增长驱动",
                    "subtitle": "光网络与AI数据中心互联（PDF 第 4 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "AI/云超大规模商 DCI 需求激增，光网络设备供需紧张。",
                                "光网络/IP 业务 2026 年增长指引 18-20%，收购 Infinera 强化战略定位。",
                                "与 NVIDIA 深度合作开发 AI-native 原生网络架构，6G 研究行业领先。",
                            ],
                        }
                    ],
                },
                {
                    "id": "06",
                    "title": "估值与三档目标价模型",
                    "subtitle": "当前价约 $13.95（PDF 第 7 页）",
                    "blocks": [
                        {
                            "type": "scenario_cards",
                            "items": [
                                {"key": "bull", "label": "乐观情景", "probability": "35%", "range": "$18–$22", "text": "AI/cloud需求超预期，Optical持续高增长。"},
                                {"key": "base", "label": "基准情景", "probability": "45%", "range": "$13–$16", "text": "网络基建12-14%增速，毛利率稳定。"},
                                {"key": "bear", "label": "悲观情景", "probability": "20%", "range": "$7–$10", "text": "运营商CapEx放缓、竞争加剧、地缘冲击。"},
                            ],
                        }
                    ],
                },
                {
                    "id": "09",
                    "title": "操作建议",
                    "subtitle": "持有/择机买入（PDF 第 8 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "加仓区域：$11.5-$12.5；止盈：$15+；止损：$10-$11。",
                                "组合配置 4%-8%，信心 65/100。",
                            ],
                        }
                    ],
                },
            ],
            "conclusion": "诺基亚正从 5G 周期低谷转向 AI 基础设施驱动复苏，光网络转型故事提供上行空间；但传统电信周期属性仍在，适合中长期投资者逢低配置。",
        },
    },
    {
        "code": "RKLB",
        "card": {
            "code": "RKLB",
            "name": "Rocket Lab",
            "tagline": "垂直整合的太空发射与卫星系统",
            "institution": "香港沐龙资产管理有限公司",
            "report_date": "2026-05-18",
            "quote_symbol": "RKLB",
            "scenarios": [
                {"key": "bull", "label": "乐观情景", "probability": "35%", "subtitle": "Neutron首飞成功", "range_low": 180, "range_high": 220, "note": "PDF：$180-$220"},
                {"key": "base", "label": "基准情景", "probability": "45%", "subtitle": "Neutron按计划推进", "range_low": 110, "range_high": 140, "note": "PDF：$110-$140"},
                {"key": "bear", "label": "悲观情景", "probability": "20%", "subtitle": "Neutron延误/失败", "range_low": 50, "range_high": 80, "note": "PDF：$50-$80"},
            ],
            "highlights": [
                "Q1 2026 营收 $200.3M（YoY +63.5%），首次突破 $200M 大关",
                "毛利率 38.2% 创历史新高，订单储备 Backlog $2.2B",
                "Space Systems $136.7M（68%）+ Launch Services $63.7M（32%）",
                "Neutron 中运力火箭目标 2026 Q4 首飞，将大幅扩大 TAM",
                "核心风险：Neutron 执行、现金消耗、发射失败、国防预算波动",
            ],
            "pdf_path": "RKLB 美股分析报告.pdf",
        },
        "report": {
            "sections": [
                {
                    "id": "01",
                    "title": "基本面数据快照",
                    "subtitle": "Q1 2026 创纪录季度（PDF 第 3 页）",
                    "blocks": [
                        {
                            "type": "stat_cards",
                            "layout": "4",
                            "items": [
                                {"icon": "chart", "title": "总营收", "value": "$200.3M", "lines": ["YoY +63.5%"]},
                                {"icon": "shield", "title": "毛利率", "value": "38.2%", "lines": ["创历史新高"]},
                                {"icon": "layers", "title": "Space Systems", "value": "$136.7M", "lines": ["占比 ~68%"]},
                                {"icon": "rocket", "title": "订单储备", "value": "$2.2B", "lines": ["同比大幅增长"]},
                            ],
                        }
                    ],
                },
                {
                    "id": "02",
                    "title": "增长驱动与Neutron催化剂",
                    "subtitle": "垂直整合与国防需求（PDF 第 4-5 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "Electron 火箭小运力市场领先，50+ 次成功发射验证可靠性。",
                                "国防与政府合同（SDA、高超音速等）需求强劲。",
                                "Neutron 13,000kg+ 至 LEO，2026 Q4 首飞是最大增长催化剂。",
                                "端到端垂直整合：制造-发射-卫星运营全链条差异化壁垒。",
                            ],
                        }
                    ],
                },
                {
                    "id": "06",
                    "title": "估值与三档目标价模型",
                    "subtitle": "当前价约 $120-125（PDF 第 7 页）",
                    "blocks": [
                        {
                            "type": "scenario_cards",
                            "items": [
                                {"key": "bull", "label": "乐观情景", "probability": "35%", "range": "$180–$220", "text": "Neutron成功首飞并快速量产。"},
                                {"key": "base", "label": "基准情景", "probability": "45%", "range": "$110–$140", "text": "Neutron按计划推进，Backlog正常转化。"},
                                {"key": "bear", "label": "悲观情景", "probability": "20%", "range": "$50–$80", "text": "Neutron延误/失败、发射事故、国防预算削减。"},
                            ],
                        }
                    ],
                },
                {
                    "id": "09",
                    "title": "操作建议",
                    "subtitle": "择机买入/持有（PDF 第 8 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "加仓区域：$100-$110；谨慎获利：$140+；止损：$90-$100。",
                                "高波动成长股，仓位 3%-7%，信心 60/100。",
                            ],
                        }
                    ],
                },
            ],
            "conclusion": "Rocket Lab 订单储备强劲、毛利持续改善，Neutron 首飞将打开巨大市场空间；但执行风险高、现金消耗大，仅适合高风险承受力投资者密切跟踪。",
        },
    },
    {
        "code": "IBM",
        "card": {
            "code": "IBM",
            "name": "IBM",
            "tagline": "关键基础设施软件与混合云防守型价值股",
            "institution": "香港沐龙资产管理有限公司",
            "report_date": "2026-06-02",
            "quote_symbol": "IBM",
            "scenarios": [
                {"key": "bull", "label": "乐观情景", "probability": "15%", "subtitle": "AI订单持续超预期", "range_low": 400, "range_high": 449, "note": "PDF：$400-$449"},
                {"key": "base", "label": "基准情景", "probability": "60%", "subtitle": "营收增长5-6%", "range_low": 325, "range_high": 355, "note": "PDF：$325-$355"},
                {"key": "bear", "label": "悲观情景", "probability": "25%", "subtitle": "AI增速放缓/大型机回落", "range_low": 240, "range_high": 280, "note": "PDF：$240-$280"},
            ],
            "highlights": [
                "2026 Q1 营收 $159.2亿（YoY +9%），Non-GAAP EPS $1.91（YoY +19%）",
                "软件部门 $70.52亿（YoY +11%），占比 44.3% 成最大收入来源",
                "AI 相关软件与服务收入同比 +40%，RPO 达 $680亿",
                "股息率 ~2.65%，前瞻 PE ~26-27x（13年来首次超越微软）",
                "核心风险：估值透支、大型机脉冲回落、CFO 高位减持信号",
            ],
            "pdf_path": "IBM (IBM) 投资分析报告.pdf",
        },
        "report": {
            "sections": [
                {
                    "id": "01",
                    "title": "基本面数据快照",
                    "subtitle": "2026 Q1 全面超预期（PDF 第 2-4 页）",
                    "blocks": [
                        {
                            "type": "stat_cards",
                            "layout": "4",
                            "items": [
                                {"icon": "chart", "title": "总营收", "value": "$159.2亿", "lines": ["YoY +9%"]},
                                {"icon": "cash", "title": "Non-GAAP EPS", "value": "$1.91", "lines": ["YoY +19%"]},
                                {"icon": "layers", "title": "软件部门", "value": "$70.52亿", "lines": ["YoY +11%", "占比 44.3%"]},
                                {"icon": "bolt", "title": "AI 相关收入", "value": "+40%", "lines": ["同比高增长"]},
                            ],
                        }
                    ],
                },
                {
                    "id": "02",
                    "title": "需求端与AI/量子双轮驱动",
                    "subtitle": "结构性转型成果（PDF 第 5-6 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "软件连续多季度 10%+ 增长，2026 全年指引上调至 10% 以上。",
                                "混合云自动化基建软件深耕企业级复杂环境，迁移成本极高。",
                                "量子计算获美国联邦政府 $10亿 承诺，未来五年投入超 $100亿。",
                                "短期靠 AI 变现稳基本盘，长期靠量子计算打开第二增长曲线。",
                            ],
                        }
                    ],
                },
                {
                    "id": "06",
                    "title": "估值与三档目标价模型",
                    "subtitle": "当前价约 $309（PDF 第 8-9 页）",
                    "blocks": [
                        {
                            "type": "scenario_cards",
                            "items": [
                                {"key": "bull", "label": "乐观情景", "probability": "15%", "range": "$400–$449", "text": "AI订单持续超预期，软件增长强劲。"},
                                {"key": "base", "label": "基准情景", "probability": "60%", "range": "$325–$355", "text": "全年营收5-6%稳健增长，符合指引。"},
                                {"key": "bear", "label": "悲观情景", "probability": "25%", "range": "$240–$280", "text": "AI增速放缓、大型机脉冲回落、宏观下行。"},
                            ],
                        }
                    ],
                },
                {
                    "id": "09",
                    "title": "操作建议",
                    "subtitle": "持有观望，等待修正（PDF 第 10-11 页）",
                    "blocks": [
                        {
                            "type": "bullets",
                            "items": [
                                "当前 $309 观望为主；建仓区间 $280-$295；加仓 $260-$280。",
                                "止盈 $355-$375；止损跌破 $240。",
                                "评级 C：估值合理偏高，信心中等偏低，以股息为安全边际。",
                            ],
                        }
                    ],
                },
            ],
            "conclusion": "IBM 软件转型与 AI 变现已验证阶段性成果，兼具高股息防守属性；但六周内估值快速重估已超越微软，当前价位追高风险收益比弱化，建议持有观望、等待回调再布局。",
        },
    },
]


def main() -> None:
    for spec in SPECS:
        code = spec["code"]
        card = spec["card"]
        report = {
            "code": code,
            "name": card["name"],
            "tagline": card["tagline"],
            "institution": card["institution"],
            "report_date": card["report_date"],
            **spec["report"],
        }
        card_path = DATA / f"{code.lower()}_research_card.json"
        report_path = DATA / f"{code.lower()}_research_report.json"
        card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("wrote", card_path.name, report_path.name)


if __name__ == "__main__":
    main()
