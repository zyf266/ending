"""从 PDF 提取文本生成完整 *_research_report.json（与 NVDA 同级结构）。"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent


def save(code: str, payload: dict) -> None:
    path = DATA / f"{code.lower()}_research_report.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", path.name, "sections", len(payload.get("sections", [])))


CRCL = {
    "code": "CRCL",
    "name": "Circle",
    "tagline": "连接传统金融与区块链的稳定币基石",
    "institution": "沐龙量化研究",
    "report_date": "2026-05-20",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：稳健增长，盈利能力改善",
            "subtitle": "最新季度：Q1 2026（截至2026年3月31日）",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "总营收及储备收入", "value": "$694M", "lines": ["YoY +20%"]},
                        {"icon": "trend", "title": "Adjusted EPS", "value": "$0.47", "lines": ["大幅 beat 预期"]},
                        {"icon": "layers", "title": "Adjusted EBITDA", "value": "$151M", "lines": ["YoY +24%", "margin 53%"]},
                        {"icon": "cash", "title": "USDC 流通量", "value": "$770亿", "lines": ["YoY +28%"]},
                    ],
                },
                {
                    "type": "dual_footer",
                    "items": [
                        {"icon": "flow", "title": "链上交易量", "text": "$21.5万亿（YoY +263%），反映 USDC 在支付与 DeFi 中的核心媒介地位。"},
                        {"icon": "network", "title": "新增长点", "text": "Arc 区块链网络及相关产品，为长期收入多元化与生态卡位提供增量。"},
                    ],
                },
            ],
        },
        {
            "id": "01b",
            "title": "基本面数据快照：财务健康，处于扩张早期",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "cash", "title": "储备雄厚", "text": "USDC 储备主要为现金及短期美债，安全性极高，资产结构稳健。"},
                        {"icon": "chart", "title": "财务健康", "text": "负债率维持低位，自由现金流健康，具备充足运营资金与发展潜力。"},
                        {"icon": "trend", "title": "盈利能力", "text": "ROE/ROIC 持续改善，业务盈利效率与资本回报稳步提升。"},
                        {"icon": "calendar", "title": "IPO 后波动", "text": "2025 年 6 月上市后经历较高波动，需区分一次性因素与基本面趋势。"},
                        {"icon": "rocket", "title": "稳健复苏", "text": "2026 年 USDC 采用率提升及 Arc 生态推进，营收实现稳健增长。"},
                        {"icon": "stack", "title": "早期阶段", "text": "仍处规模扩张与收入多元化早期，长期增长空间广阔，战略清晰。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动：多场景驱动需求强劲",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心产品/业务需求",
                            "items": [
                                {"icon": "cash", "title": "USDC 稳定币", "text": "跨境支付、B2B 结算、DeFi 及 Agentic AI 的核心媒介。"},
                                {"icon": "network", "title": "Arc 区块链网络", "text": "高性能合规基础设施，降低企业上链门槛。"},
                                {"icon": "globe", "title": "支付网络与企业应用", "text": "连接传统企业与链上生态，推动实体与数字金融融合。"},
                            ],
                        },
                        {
                            "title": "供给 vs. 需求",
                            "items": [
                                {"icon": "stack", "title": "Tokenized 基金 (USYC)", "text": "传统基金份额代币化，提升流动性与交易效率。"},
                                {"icon": "target", "title": "合规决定供给", "text": "监管合规与储备透明度是市场准入核心门槛。"},
                                {"icon": "chart", "title": "需求匹配度高", "text": "产品矩阵与全球机构及零售真实需求高度匹配。"},
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "需求端与增长驱动：长期催化剂与市场地位",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chip", "title": "Arc L1 网络", "text": "合规高性能底层，支撑生态高效运转与创新落地。"},
                        {"icon": "robot", "title": "Agentic AI 基础设施", "text": "为 AI 智能体经济活动构建标准化价值交换协议。"},
                        {"icon": "globe", "title": "传统金融渗透", "text": "稳定币在机构资产配置中的渗透率持续提升。"},
                        {"icon": "flow", "title": "跨境支付替代", "text": "低成本秒级全球资金流转，替代昂贵缓慢的跨境通道。"},
                        {"icon": "trophy", "title": "全球第二大稳定币", "text": "USDC 在交易、DeFi 等场景占据核心流通媒介地位。"},
                        {"icon": "target", "title": "合规优势显著", "text": "与多地监管沟通紧密，审计机制完善，为机构首选合规稳定币。"},
                    ],
                }
            ],
        },
        {
            "id": "02c",
            "title": "需求端与增长驱动：竞争格局与护城河",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "Tether (USDT)", "text": "规模最大，但透明度与全球合规性存在短板，长期面临监管质疑。"},
                        {"icon": "globe", "title": "传统支付巨头", "text": "Visa、PayPal 等布局稳定币，Circle 在链上原生基础设施与网络效应领先。"},
                        {"icon": "layers", "title": "其他稳定币", "text": "PYUSD 等规模较小，短期内难以撼动 USDC 份额。"},
                        {"icon": "stack", "title": "护城河强度", "text": "合规、透明度、全栈基础设施多维度叠加，壁垒较为坚固。"},
                    ],
                },
                {
                    "type": "dual_footer",
                    "items": [
                        {"icon": "target", "title": "监管牌照与合规", "text": "持有多国合规牌照，在监管框架内运营，行业标准领先。"},
                        {"icon": "cash", "title": "储备透明度", "text": "储备资产定期第三方审计，资金流向清晰，透明度极高。"},
                    ],
                },
            ],
        },
        {
            "id": "03",
            "title": "区域/地缘与风险变量：全球市场与监管风险",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "rocket", "title": "新兴市场驱动", "text": "跨境支付需求是业务增长重要引擎，采用率较高。"},
                        {"icon": "globe", "title": "中国大陆现状", "text": "受当地监管限制，需在合规框架下探索潜在机会。"},
                        {"icon": "chart", "title": "核心贡献地区", "text": "美国及欧洲为主要营收来源，新兴市场具长期潜力。"},
                        {"icon": "line", "title": "系统性风险", "text": "稳定币面临波动、挤兑等潜在系统性挑战，需持续监控。"},
                    ],
                }
            ],
        },
        {
            "id": "03b",
            "title": "区域/地缘与风险变量：监管是最大变量",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "target", "title": "政策不确定性", "text": "全球稳定币监管框架仍在形成，政策变化或致业务模式重构。"},
                        {"icon": "factory", "title": "合规成本攀升", "text": "本地化合规投入持续增加，可能压缩利润空间。"},
                        {"icon": "globe", "title": "储备资产安全", "text": "地缘紧张或影响美债储备流动性，需建立风险对冲机制。"},
                        {"icon": "chart", "title": "监管风险", "text": "美国及全球加密监管变化是最大风险源，直接影响业务合规性。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力与毛利率防守：利率与规模双驱动",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "Adjusted EBITDA Margin", "value": "53%", "lines": ["储备利息 + 平台服务费"]},
                        {"icon": "trend", "title": "核心驱动", "value": "利率 + 规模", "lines": ["美债收益率", "USDC 流通扩张", "Arc 增长"]},
                        {"icon": "layers", "title": "盈利质量", "value": "运营杠杆", "lines": ["收入多元化", "边际成本摊薄"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "管理层指引与语气分析：乐观且具战略性",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "calendar", "title": "最新指引", "text": "维持 2026 全年指引；强调 Arc 等新业务收入尚未完全计入报表。"},
                        {"icon": "rocket", "title": "管理层语气", "text": "CEO 基调乐观，突出 Agentic AI、Arc 生态与企业客户采用加速。"},
                        {"icon": "trophy", "title": "历史准确性", "text": "IPO 后指引准确性逐步改善，Q1 符合预期，增强市场信任。"},
                        {"icon": "chart", "title": "预期前置", "text": "高增长预期已部分反映在股价，监管或利率变化或引发短期波动。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值与三档目标价模型（12–18 个月）",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "当前股价", "value": "~$111", "lines": ["2026-05-20"]},
                        {"icon": "layers", "title": "Forward PE", "value": "较高区间", "lines": ["高成长金融科技溢价"]},
                        {"icon": "trend", "title": "Fintech 溢价", "value": "显著", "lines": ["技术壁垒与生态卡位获认可"]},
                    ],
                },
                {
                    "type": "scenarios",
                    "items": [
                        {"key": "bull", "label": "乐观情景", "probability": "~35%", "subtitle": "上行驱动", "range_low": 180, "range_high": 240, "note": "USDC 超预期、Arc 大规模采用、Agentic AI 落地、利率友好"},
                        {"key": "base", "label": "基准情景", "probability": "~45%", "subtitle": "中性预期", "range_low": 120, "range_high": 160, "note": "USDC 稳健增长、多元化收入兑现、正常监管环境"},
                        {"key": "bear", "label": "悲观情景", "probability": "~20%", "subtitle": "下行风险", "range_low": 60, "range_high": 90, "note": "监管收紧、加密熊市、利率下行压制储备收益"},
                    ],
                },
                {
                    "type": "p",
                    "text": "当前价位风险收益比较为平衡，上行高度依赖合规框架下的执行力与全球监管演变；建议关注 USDC 流通量、Arc 进展等催化剂。",
                },
            ],
        },
        {
            "id": "07",
            "title": "操作建议与风险管理",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "回调加仓", "text": "$95–$105 区域可分批加仓，摊薄持仓成本。"},
                        {"icon": "target", "title": "谨慎获利", "text": "$130+ 可考虑部分获利，锁定收益、降低波动风险。"},
                        {"icon": "layers", "title": "核心仓位", "text": "建议组合占比 4–8%，成长型基础设施仓位。"},
                        {"icon": "line", "title": "止盈止损", "text": "止损 $85–$90；$160+ 分批减仓；可用期权对冲监管与系统性风险。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业叠加与综合情景",
            "blocks": [
                {
                    "type": "p",
                    "text": "利率环境直接影响储备收入；稳定币在波动市场中具支付工具韧性。区块链与稳定币处快速发展周期，机构采用率提升，但监管不确定性仍是最大变量。短期看财报与 Arc 进展，长期看稳定币成为互联网金融基础设施。最终建议：择机买入/持有（信心 62/100）；适合看好合规稳定币与区块链金融基础设施、并能严格仓位管理的投资者。",
                }
            ],
        },
    ],
    "conclusion": "Circle 受益于 USDC 合规领先与储备收益模型，Arc 打开第二增长曲线；核心风险为监管政策与利率环境。建议持有为主、回调加仓，严格跟踪 USDC 流通量、储备透明度与全球监管动态。",
}

# INTC / SNDK / ETH / HYPE — 结构与 PDF 对齐（略去重复注释）
INTC = {
    "code": "INTC",
    "name": "英特尔",
    "tagline": "AI时代战争转折与复苏",
    "institution": "沐龙量化研究",
    "report_date": "2026-05-20",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：业绩超预期，逐步复苏",
            "subtitle": "最新季度：Q1 2026（截至2026年3月28日）",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "总营收", "value": "$136亿", "lines": ["YoY +7%", "大幅 beat"]},
                        {"icon": "trend", "title": "Non-GAAP EPS", "value": "$0.29", "lines": ["YoY +123%"]},
                        {"icon": "server", "title": "DCAI", "value": "$51亿", "lines": ["YoY +22%", "AI CPU 驱动"]},
                        {"icon": "factory", "title": "Intel Foundry", "value": "$54亿", "lines": ["外部收入 $1.74亿"]},
                    ],
                },
                {
                    "type": "dual_footer",
                    "items": [
                        {"icon": "chip", "title": "CCG", "text": "Client Computing $77亿（约 57%），PC 市场稳健。"},
                        {"icon": "line", "title": "GAAP EPS", "text": "-$0.73，受重组与 Mobileye 减值等一次性因素拖累。"},
                    ],
                },
            ],
        },
        {
            "id": "01b",
            "title": "基本面数据快照：转型阵痛与未来引擎",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "cash", "title": "现金承压", "text": "Q1 调整后 FCF 约 -$20亿，高额 CapEx 短期考验流动性。"},
                        {"icon": "chart", "title": "负债率上升", "text": "为制程追赶与产能扩张，杠杆有所提升。"},
                        {"icon": "trend", "title": "盈利修复", "text": "ROE/ROIC 脱离低谷，随新产能与成本控制稳步修复。"},
                        {"icon": "rocket", "title": "复苏开启", "text": "2025–2026 进入复苏阶段，需求回暖带动业绩反弹。"},
                        {"icon": "server", "title": "新增长引擎", "text": "DC&AI 重回增长，Foundry 成为第二曲线。"},
                        {"icon": "factory", "title": "转型阵痛", "text": "18A 量产爬坡期，高资本支出，成效需时间验证。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动：AI 驱动复苏",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心产品/业务需求",
                            "items": [
                                {"icon": "chip", "title": "AI PC CPU", "text": "AI PC 渗透率提升，拉动高性能终端需求。"},
                                {"icon": "server", "title": "数据中心 AI CPU", "text": "Gaudi 与 Xeon 在推理/训练需求复苏。"},
                                {"icon": "factory", "title": "Intel 18A 代工", "text": "西方世界寻求先进制程供应链安全的重要选择。"},
                            ],
                        },
                        {
                            "title": "供给 vs. 需求",
                            "items": [
                                {"icon": "layers", "title": "产能释放", "text": "18A 量产爬坡，良率提升，供给能力逐步释放。"},
                                {"icon": "globe", "title": "全球产能紧张", "text": "2nm/3nm 节点紧张，地缘加剧供应链不确定性。"},
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
                        {"icon": "chip", "title": "18A/14A 量产", "text": "制程竞争力重定义的关键。"},
                        {"icon": "factory", "title": "Foundry 客户扩张", "text": "获取苹果、高通等外部大单是破局重点。"},
                        {"icon": "globe", "title": "CHIPS Act", "text": "巨额补贴缓解资本开支压力。"},
                        {"icon": "rocket", "title": "AI PC 渗透", "text": "换机潮拉动高性能芯片需求。"},
                        {"icon": "trophy", "title": "Foundry 目标", "text": "3–5 年内挑战台积电、三星，重塑代工格局。"},
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
                        {"icon": "chip", "title": "NVIDIA", "text": "GPU 主导，Intel 在 CPU/加速器与其互补。"},
                        {"icon": "server", "title": "AMD", "text": "EPYC 在数据中心持续施压。"},
                        {"icon": "factory", "title": "TSMC / Samsung", "text": "Foundry 制程与良率领先。"},
                        {"icon": "stack", "title": "IDM+Foundry", "text": "x86 生态与本土先进制程是核心资产；18A 成功是护城河关键。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "地缘/供应链风险",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "中国市场", "text": "收入占比仍高，出口管制限制高端芯片销售。"},
                        {"icon": "factory", "title": "供应链风险", "text": "全球化制造物流任何环节中断均加剧不确定性。"},
                        {"icon": "target", "title": "出口管制", "text": "中美科技脱钩加剧，迫使产品线与区域策略调整。"},
                        {"icon": "chart", "title": "主要市场", "text": "美国及盟国是基本盘，中国风险需常态化监控。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力与毛利率：逐步增强",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "Q1 Non-GAAP 毛利率", "value": "41%", "lines": ["优于指引"]},
                        {"icon": "chip", "title": "驱动因素", "value": "结构优化", "lines": ["高价值 AI 芯片占比", "精准定价"]},
                        {"icon": "factory", "title": "Foundry 拖累", "value": "短期", "lines": ["量产爬坡折旧与研发较高"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "管理层指引与语气分析",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "calendar", "title": "Q2 指引", "text": "营收 $138–148亿，Non-GAAP EPS $0.20，复苏信号强劲。"},
                        {"icon": "rocket", "title": "CEO 语气", "text": "2026 是执行之年，对 AI 与 18A 进展乐观务实。"},
                        {"icon": "trophy", "title": "指引准确性", "text": "Q1 大幅超越此前指引，修复市场信任。"},
                        {"icon": "chart", "title": "预期评估", "text": "转型预期处高位，18A 执行偏差或引发回调。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值与三档目标价模型（12–18 个月）",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "当前股价", "value": "~$110", "lines": ["2026-05-19"]},
                        {"icon": "layers", "title": "Forward PE", "value": "较高", "lines": ["转型期利润基数偏低"]},
                        {"icon": "trend", "title": "PB", "value": "修复中", "lines": ["距历史中枢仍有空间"]},
                    ],
                },
                {
                    "type": "scenarios",
                    "items": [
                        {"key": "bull", "label": "乐观情景", "probability": "~30%", "subtitle": "上行驱动", "range_low": 150, "range_high": 180, "note": "18A 良率超预期、Foundry 获大单、AI CPU 份额回升"},
                        {"key": "base", "label": "基准情景", "probability": "~45%", "subtitle": "中性预期", "range_low": 90, "range_high": 120, "note": "18A 按计划爬坡，Foundry 亏损逐步收窄"},
                        {"key": "bear", "label": "悲观情景", "probability": "~25%", "subtitle": "下行风险", "range_low": 50, "range_high": 70, "note": "18A 不及预期、Foundry 持续亏损、份额流失"},
                    ],
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
                        {"icon": "chart", "title": "回调加仓", "text": "$95–$100 企稳可分批加仓。"},
                        {"icon": "target", "title": "谨慎获利", "text": "$130+ 考虑部分获利。"},
                        {"icon": "layers", "title": "仓位", "text": "组合 4–7%，转型复苏观察仓位。"},
                        {"icon": "line", "title": "风控", "text": "止损 $85–$90；止盈 $140+ 分批；可用期权对冲地缘风险。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业叠加与综合情景",
            "blocks": [
                {
                    "type": "p",
                    "text": "低利率利好 CapEx，AI 结构性需求提供增长缓冲；CHIPS Act 支撑本土产能。短期看 18A 与财报，长期看 Foundry 转型与 AI CPU 第二曲线。评级：择机持有/谨慎买入（信心 55/100）；适合看好美国半导体供应链自主化、能承受高执行风险的长期投资者。",
                }
            ],
        },
    ],
    "conclusion": "英特尔处于 AI 与制造复苏交汇点，18A 量产与 Foundry 客户落地是关键拐点；需严格跟踪毛利率、现金流与竞争格局。",
}

SNDK = {
    "code": "SNDK",
    "name": "SanDisk",
    "tagline": "AI存储周期节点的核心受益者",
    "institution": "沐龙量化研究",
    "report_date": "2026-05-20",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：业绩爆炸式增长",
            "subtitle": "最新季度：FY2026 Q3（截至2026年4月3日）",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "总营收", "value": "$59.5亿", "lines": ["QoQ +97%", "YoY +251%"]},
                        {"icon": "trend", "title": "Non-GAAP EPS", "value": "$23.41", "lines": ["大幅超预期"]},
                        {"icon": "layers", "title": "Non-GAAP 毛利率", "value": "78.4%", "lines": ["QoQ +27.3ppt"]},
                        {"icon": "server", "title": "Data Center (AI SSD)", "value": "$14.67亿", "lines": ["QoQ +233%"]},
                    ],
                }
            ],
        },
        {
            "id": "01b",
            "title": "从周期低谷到超级增长",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "flow", "title": "现金流强劲", "text": "Q3 运营现金流 $30.4亿，调整后 FCF $29.55亿。"},
                        {"icon": "cash", "title": "财务健康", "text": "现金充裕，负债率极低，抗风险能力强。"},
                        {"icon": "trophy", "title": "盈利质量", "text": "ROE/ROIC 随利润爆发大幅提升。"},
                        {"icon": "rocket", "title": "快速转向", "text": "2025 分拆后敏捷调整，驶入超级增长快车道。"},
                        {"icon": "chip", "title": "AI 驱动", "text": "2026 抓住 NAND 短缺，量价齐升创纪录。"},
                        {"icon": "stack", "title": "战略转型", "text": "从传统存储向 AI 企业存储解决方案提供商转型。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动：AI 存储需求爆炸",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心需求",
                            "items": [
                                {"icon": "server", "title": "企业级 SSD", "text": "AI 训练/推理对高带宽大容量存储需求爆炸式增长。"},
                                {"icon": "chip", "title": "先进 3D NAND", "text": "BiCS8 等制程构筑技术壁垒。"},
                            ],
                        },
                        {
                            "title": "供给 vs. 需求",
                            "items": [
                                {"icon": "factory", "title": "严重短缺", "text": "2026 全行业 NAND 供给不足，库存低位，主流产品售罄。"},
                                {"icon": "chart", "title": "定价权", "text": "供需错配下具备极强定价能力与毛利传导。"},
                                {"icon": "line", "title": "可持续性", "text": "Hyperscaler 多年 AI 基建投资驱动，非短期脉冲。"},
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "长期催化剂与市场份额",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chart", "title": "渗透率提升", "text": "AI 数据中心 SSD 渗透率持续提升。"},
                        {"icon": "chip", "title": "BiCS9 迭代", "text": "更高密度 NAND 带来成本下降与性能跃升。"},
                        {"icon": "target", "title": "长期供货锁定", "text": "与云厂商长单锁定未来收入。"},
                        {"icon": "trophy", "title": "份额扩张", "text": "企业级 NAND SSD 市场份额稳步提升。"},
                        {"icon": "trend", "title": "份额 CAGR", "text": "预计未来三年份额年复合增长 5%+。"},
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
                        {"icon": "factory", "title": "Samsung / SK", "text": "韩系厂商产能与技术实力强劲。"},
                        {"icon": "stack", "title": "Micron / Kioxia", "text": "同业在 enterprise SSD 激烈竞争。"},
                        {"icon": "chip", "title": "技术壁垒", "text": "BiCS 路线与控制器能力构成差异化。"},
                        {"icon": "server", "title": "客户绑定", "text": "与头部云/ OEM 深度合作关系。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "地缘/供应链与周期风险",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "地缘与关税", "text": "贸易政策变化或影响成本与出货节奏。"},
                        {"icon": "factory", "title": "产能周期", "text": "行业扩产可能导致未来价格回落。"},
                        {"icon": "chart", "title": "客户集中度", "text": "大客户订单波动影响短期业绩。"},
                        {"icon": "line", "title": "股价波动", "text": "存储股高 Beta，需严格止损纪律。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力与毛利率",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "毛利率", "value": "78.4%", "lines": ["历史极高水平"]},
                        {"icon": "trend", "title": "运营杠杆", "value": "显著", "lines": ["收入回升阶段利润增速更快"]},
                        {"icon": "layers", "title": "产品结构", "value": "AI SSD", "lines": ["高毛利品类占比提升"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "管理层指引与语气",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "calendar", "title": "指引", "text": "管理层对 AI 存储需求与供给紧张态度积极。"},
                        {"icon": "rocket", "title": "语气", "text": "强调企业级 SSD 与 BiCS 路线图执行。"},
                        {"icon": "trophy", "title": "业绩兑现", "text": "连续超预期增强市场信心。"},
                        {"icon": "chart", "title": "估值风险", "text": "股价已反映部分周期高点预期。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值与三档目标价模型",
            "blocks": [
                {
                    "type": "scenarios",
                    "items": [
                        {"key": "bull", "label": "乐观情景", "probability": "~35%", "subtitle": "周期延续", "range_low": 280, "range_high": 350, "note": "NAND 短缺延续、AI SSD 量价齐升"},
                        {"key": "base", "label": "基准情景", "probability": "~45%", "subtitle": "中性", "range_low": 200, "range_high": 260, "note": "需求稳健、毛利率高位略回落"},
                        {"key": "bear", "label": "悲观情景", "probability": "~20%", "subtitle": "周期拐点", "range_low": 120, "range_high": 160, "note": "扩产导致价格下行、需求不及预期"},
                    ],
                }
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
                        {"icon": "chart", "title": "顺势持有", "text": "周期上行阶段以持有为主，避免盲目追高。"},
                        {"icon": "target", "title": "分批止盈", "text": "接近乐观区间可分批锁定利润。"},
                        {"icon": "layers", "title": "仓位", "text": "建议 3–6%，与 MU/存储板块分散配置。"},
                        {"icon": "line", "title": "止损", "text": "跌破关键支撑严格止损，防范周期反转。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业叠加",
            "blocks": [
                {
                    "type": "p",
                    "text": "SNDK 与 AI 资本开支、NAND 供需、半导体周期高度联动。宜在景气上行持有，密切跟踪库存、合约价与云厂商 CapEx 指引。",
                }
            ],
        },
    ],
    "conclusion": "SanDisk 是 AI 存储景气核心受益者，短期供给紧张支撑盈利；需警惕周期拐点与估值透支，严格执行仓位与止损。",
}

ETH = {
    "code": "ETH",
    "name": "以太坊",
    "tagline": "全球智能合约与数字基础设施",
    "institution": "沐龙量化研究",
    "report_date": "2026-05-20",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：链上指标与供应机制",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "年化通胀", "value": "~0.23%", "lines": ["温和通缩倾向"]},
                        {"icon": "stack", "title": "Staking", "value": "~36M+ ETH", "lines": ["占比 ~30%"]},
                        {"icon": "network", "title": "DeFi TVL", "value": "$430–450亿", "lines": ["占比 ~53%"]},
                        {"icon": "rocket", "title": "Pectra 后", "value": "扩展性提升", "lines": ["L2 活动显著增长"]},
                    ],
                }
            ],
        },
        {
            "id": "01b",
            "title": "机构持仓与 ETF 动向",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "trophy", "title": "BitMine 持仓", "text": "528 万 ETH（占供应 4.37%），成本约 $3050–3450，浮亏未减仓。"},
                        {"icon": "chart", "title": "ETH ETF", "text": "2026 年至今净流入为负，高位抛压压制上行。"},
                        {"icon": "target", "title": "机构信号", "text": "部分机构小额加仓，显示长期信念。"},
                        {"icon": "line", "title": "资金面", "text": "需关注 ETF 回流，持续恶化或拖累 Beta。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "chip", "title": "智能合约", "text": "可编程性是去中心化生态底层。"},
                        {"icon": "flow", "title": "DeFi", "text": "借贷、交易等金融服务的核心平台。"},
                        {"icon": "globe", "title": "RWA", "text": "真实世界资产代币化首选底层。"},
                        {"icon": "cash", "title": "稳定币", "text": "USDC 等发行核心网络，链上价值锚定。"},
                        {"icon": "network", "title": "Layer 2", "text": "扩容缓解主网拥堵，匹配海量交易需求。"},
                        {"icon": "robot", "title": "Agentic AI", "text": "AI 智能体链上协作经济基础。"},
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "长期催化剂与市场地位",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "stack", "title": "后续升级", "text": "Glamsterdam 等优化吞吐与安全。"},
                        {"icon": "globe", "title": "RWA 规模化", "text": "房地产、债券等资产链上化加速。"},
                        {"icon": "chart", "title": "Staking ETF", "text": "机构通过 ETF 参与质押成趋势。"},
                        {"icon": "cash", "title": "稳定币扩张", "text": "流通市值向万亿美元级别迈进。"},
                        {"icon": "trophy", "title": "L1 份额", "text": "智能合约平台主导份额 53%+。"},
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
                        {"icon": "rocket", "title": "Solana", "text": "速度与费用优势，适合高频消费级场景。"},
                        {"icon": "chart", "title": "BNB Chain", "text": "交易所生态导流，DeFi 活跃但去中心化程度较低。"},
                        {"icon": "network", "title": "开发者生态", "text": "ETH 开发者网络与工具链仍最深厚。"},
                        {"icon": "stack", "title": "护城河", "text": "安全记录、L2 矩阵与质押经济形成复合壁垒。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "监管与宏观风险",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "监管政策", "text": "美国及全球加密监管影响 ETF 与机构入场。"},
                        {"icon": "chart", "title": "BTC 联动", "text": "风险偏好与比特币走势显著影响 ETH Beta。"},
                        {"icon": "line", "title": "利率流动性", "text": "宏观流动性收紧压制风险资产估值。"},
                        {"icon": "target", "title": "技术风险", "text": "升级执行、L2 安全与 MEV 需持续跟踪。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利质量（链上经济）",
            "blocks": [
                {
                    "type": "p",
                    "text": "以太坊无传统公司利润表，价值捕获来自 Gas、质押收益与生态 TVL。低通胀 + 高质押率形成供应收缩，费用收入与 L2 活动是景气度核心指标。",
                }
            ],
        },
        {
            "id": "05",
            "title": "市场预期与情绪",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "chart", "title": "ETF 情绪", "text": "资金面疲软时价格易受压制。"},
                        {"icon": "rocket", "title": "生态情绪", "text": "RWA 与 L2 叙事支撑中长期乐观。"},
                        {"icon": "trophy", "title": "机构持仓", "text": "大型持仓方未减仓传递长期信号。"},
                        {"icon": "line", "title": "波动", "text": "加密资产波动大，需动态仓位管理。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值与三档目标价模型",
            "blocks": [
                {
                    "type": "scenarios",
                    "items": [
                        {"key": "bull", "label": "乐观情景", "probability": "~35%", "subtitle": "资金回流", "range_low": 4500, "range_high": 5500, "note": "ETF 净流入、RWA 爆发、宏观宽松"},
                        {"key": "base", "label": "基准情景", "probability": "~45%", "subtitle": "震荡上行", "range_low": 3200, "range_high": 4200, "note": "生态稳步增长、监管中性"},
                        {"key": "bear", "label": "悲观情景", "probability": "~20%", "subtitle": "深度调整", "range_low": 2200, "range_high": 2800, "note": "ETF 持续流出、监管收紧、BTC 走弱"},
                    ],
                }
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
                        {"icon": "chart", "title": "定投/回调买", "text": "ETF 流出期宜分批布局，避免一次性重仓。"},
                        {"icon": "target", "title": "止盈", "text": "接近乐观区间分批减仓。"},
                        {"icon": "layers", "title": "仓位", "text": "加密仓位建议 5–15% 组合内，ETH 为核心配置。"},
                        {"icon": "line", "title": "风控", "text": "设置硬止损，关注 ETF 周度资金流。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业叠加",
            "blocks": [
                {
                    "type": "p",
                    "text": "ETH 与全球流动性、监管、BTC 周期及链上基本面四维联动。中长期看好智能合约龙头地位，短期以 ETF 资金流与关键阻力位为交易锚点。",
                }
            ],
        },
    ],
    "conclusion": "以太坊仍是智能合约与 DeFi 核心基础设施；短期受 ETF 资金面压制，中长期看 L2/RWA 与供应机制。建议核心配置、分批建仓、严格风控。",
}

HYPE = {
    "code": "HYPE",
    "name": "Hyperliquid",
    "tagline": "去中心化衍生品交易的领导者",
    "institution": "沐龙量化研究",
    "report_date": "2026-05-20",
    "sections": [
        {
            "id": "01",
            "title": "基本面数据快照：数据表现强劲",
            "subtitle": "最新数据（2026年5月）",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "4",
                    "items": [
                        {"icon": "chart", "title": "HYPE 价格", "value": "$47.5–48.7", "lines": []},
                        {"icon": "trophy", "title": "市值", "value": "$114–116亿", "lines": ["排名前 12–15"]},
                        {"icon": "cash", "title": "周收入", "value": "~$1400万", "lines": ["持续高位"]},
                        {"icon": "layers", "title": "Open Interest", "value": "$26亿", "lines": ["纪录高点"]},
                    ],
                }
            ],
        },
        {
            "id": "01b",
            "title": "快速崛起的顶级 DeFi 基础设施",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "cash", "title": "储备雄厚", "text": "平台储备与生态基金为长期发展提供保障。"},
                        {"icon": "target", "title": "网络安全", "text": "Staking 支撑去中心化防御体系。"},
                        {"icon": "trend", "title": "代币经济学", "text": "高收入用于回购/销毁 + Staking 激励。"},
                        {"icon": "rocket", "title": "快速崛起", "text": "2025 上线后凭低延迟体验抢占 DEX 份额。"},
                        {"icon": "chart", "title": "持续创高", "text": "RWA、预测市场与 ETF 催化收入/TVL 新高。"},
                        {"icon": "globe", "title": "战略定位", "text": "从新兴 DEX 蜕变为连接 TradFi 与 DeFi 的枢纽。"},
                    ],
                }
            ],
        },
        {
            "id": "02",
            "title": "需求端与增长驱动",
            "blocks": [
                {
                    "type": "two_columns",
                    "columns": [
                        {
                            "title": "核心需求",
                            "items": [
                                {"icon": "chart", "title": "永续合约", "text": "专业交易员对低延迟链上透明交易需求强劲。"},
                                {"icon": "globe", "title": "RWA 交易", "text": "真实资产上链拓宽市场深度。"},
                                {"icon": "robot", "title": "预测市场", "text": "吸引新用户群，扩大平台基础。"},
                            ],
                        },
                        {
                            "title": "供给匹配",
                            "items": [
                                {"icon": "chip", "title": "L1 优化", "text": "专为高频交易优化的高吞吐低延迟架构。"},
                                {"icon": "trend", "title": "活跃度攀升", "text": "OI 与 24h 成交量持续上行。"},
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "id": "02b",
            "title": "长期催化剂与市场地位",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x3",
                    "items": [
                        {"icon": "stack", "title": "RWA 交易", "text": "Tokenized 资产是未来重要增长点。"},
                        {"icon": "robot", "title": "Agentic AI", "text": "AI 交易代理带来新流量与策略。"},
                        {"icon": "chart", "title": "ETF 资金", "text": "合规增量资金推动加密市场活跃度。"},
                        {"icon": "target", "title": "预测市场", "text": "品类与规模扩张打造多元生态。"},
                        {"icon": "trophy", "title": "Perps 领先", "text": "去中心化永续赛道份额领先。"},
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
                        {"icon": "chart", "title": "dYdX / GMX", "text": "同业在流动性与产品上有竞争。"},
                        {"icon": "globe", "title": "CEX", "text": "Binance 等仍占绝对流量，链上争夺激烈。"},
                        {"icon": "chip", "title": "技术体验", "text": "订单簿性能与延迟是专业用户留存关键。"},
                        {"icon": "stack", "title": "收入回购", "text": "手续费回购机制强化代币价值捕获。"},
                    ],
                }
            ],
        },
        {
            "id": "03",
            "title": "监管与平台风险",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "globe", "title": "监管", "text": "衍生品与预测市场面临各地合规不确定性。"},
                        {"icon": "line", "title": "智能合约", "text": "需关注审计与安全事件。"},
                        {"icon": "chart", "title": "代币解锁", "text": "激励与解锁节奏影响供给压力。"},
                        {"icon": "target", "title": "竞争费率", "text": "费用战或压缩短期收入与利润率。"},
                    ],
                }
            ],
        },
        {
            "id": "04",
            "title": "盈利能力（平台经济）",
            "blocks": [
                {
                    "type": "stat_cards",
                    "layout": "3",
                    "items": [
                        {"icon": "chart", "title": "周收入", "value": "~$1400万", "lines": ["交易手续费驱动"]},
                        {"icon": "trend", "title": "回购销毁", "value": "持续", "lines": ["通缩代币供给"]},
                        {"icon": "layers", "title": "Staking", "value": "激励", "lines": ["回馈长期持有者"]},
                    ],
                }
            ],
        },
        {
            "id": "05",
            "title": "市场预期",
            "blocks": [
                {
                    "type": "icon_cards",
                    "layout": "2x2",
                    "items": [
                        {"icon": "rocket", "title": "增长叙事", "text": "RWA + 预测市场 + Perps 三位一体。"},
                        {"icon": "chart", "title": "估值", "text": "高收入平台享有溢价，对交易量敏感。"},
                        {"icon": "trophy", "title": "社区", "text": "链上原生用户粘性强。"},
                        {"icon": "line", "title": "波动", "text": "代币波动大于主流币，需控制仓位。"},
                    ],
                }
            ],
        },
        {
            "id": "06",
            "title": "估值与三档目标价模型",
            "blocks": [
                {
                    "type": "scenarios",
                    "items": [
                        {"key": "bull", "label": "乐观情景", "probability": "~35%", "subtitle": "生态扩张", "range_low": 75, "range_high": 95, "note": "OI/收入超预期、RWA 爆发"},
                        {"key": "base", "label": "基准情景", "probability": "~45%", "subtitle": "稳健增长", "range_low": 50, "range_high": 65, "note": "Perps 份额维持、收入高位"},
                        {"key": "bear", "label": "悲观情景", "probability": "~20%", "subtitle": "竞争加剧", "range_low": 28, "range_high": 38, "note": "费率战、监管、加密熊市"},
                    ],
                }
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
                        {"icon": "chart", "title": "趋势持有", "text": "景气上行以持有为主，关注周收入与 OI。"},
                        {"icon": "target", "title": "止盈", "text": "接近乐观区间分批兑现。"},
                        {"icon": "layers", "title": "仓位", "text": "建议 2–5%，属高波动卫星仓位。"},
                        {"icon": "line", "title": "风控", "text": "跌破关键支撑减仓，跟踪解锁日历。"},
                    ],
                }
            ],
        },
        {
            "id": "08",
            "title": "宏观/行业叠加",
            "blocks": [
                {
                    "type": "p",
                    "text": "HYPE 与链上衍生品景气、加密流动性及平台执行力高度相关。适合看好去中心化 Perps 与 RWA 叙事、能承受高波动的投资者，严格仓位与催化剂跟踪。",
                }
            ],
        },
    ],
    "conclusion": "Hyperliquid 在链上永续与平台收入捕获上具备先发优势；需持续跟踪交易量、回购与代币解锁，防范竞争与监管风险。",
}


def main() -> None:
    for payload in (CRCL, INTC, SNDK, ETH, HYPE):
        save(payload["code"], payload)


if __name__ == "__main__":
    main()
