from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy import stats

from ..config.settings import config
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
# 风险检查结果
class RiskCheckResult:
    approved: bool
    risk_score: float
    violations: List[str]
    warnings: List[str]
    max_position_size: float
    suggested_quantity: float
    stop_loss_price: float
    take_profit_price: float


@dataclass
# 风险价值计算结果
class VaRResult:
    var_95: float
    var_99: float
    expected_shortfall_95: float
    expected_shortfall_99: float
    confidence_level: float
    horizon_days: int


@dataclass
# 压力测试结果
class StressTestResult:
    scenario_name: str
    portfolio_impact: float
    position_impacts: Dict[str, float]
    recovery_time_estimate: int
    risk_rating: str


class RiskManager:
    def __init__(self, config, db_manager=None):
        self.config = config
        self.trading_config = config.trading
        self.db_manager = db_manager
        self._initialize_metrics()

        self.daily_pnl = 0.0
        self.daily_loss_limit = config.trading.MAX_DAILY_LOSS
        self.max_drawdown_limit = config.trading.MAX_DRAWDOWN
        self.risk_events = []

    def _initialize_metrics(self):
        self.positions: Dict[str, Dict] = {}
        self.cumulative_pnl = 0.0
        self.peak_portfolio_value = 0.0
        self.current_drawdown = 0.0
        self.daily_trade_count = 0
        self.daily_volume = 0.0
        self.last_reset_date = datetime.now().date()

    def reset_daily_metrics(self):
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.daily_pnl = 0.0
            self.daily_trade_count = 0
            self.daily_volume = 0.0
            self.last_reset_date = today
            logger.info("日度风险指标已重置")

    def calculate_position_size(self, capital: float, price: float,
                                stop_loss_pct: float = None) -> float:
        if stop_loss_pct is None:
            stop_loss_pct = self.trading_config.STOP_LOSS_PERCENT

        risk_per_trade = capital * self.trading_config.MAX_POSITION_SIZE * stop_loss_pct
        quantity = risk_per_trade / (price * stop_loss_pct)
        return min(quantity, capital * self.trading_config.MAX_POSITION_SIZE / price)

    def validate_position(self, symbol: str, margin: float, account_capital: float = None) -> bool:
        """验证仓位大小是否符合风险限制
        
        Args:
            symbol: 交易对
            margin: 保证金（以USDT为单位）
            account_capital: 账户总资金（可选）
            
        Returns:
            bool: 是否通过验证
        """
        try:
            # 检查日度风险指标
            self.reset_daily_metrics()
            
            # 【修复】计算所有持仓的总保证金，而不仅仅是当前交易对的保证金
            # 这样可以防止多个交易对累计超过5%限制
            total_margin_used = sum(pos.get('margin', 0.0) for pos in self.positions.values())
            
            # 计算当前交易对已占用的保证金
            current_margin = self.positions.get(symbol, {}).get('margin', 0.0)
            # 如果当前交易对已有持仓，需要减去当前持仓的保证金，再加上新的保证金
            # 如果当前交易对没有持仓，直接加上新的保证金
            total_margin_after = total_margin_used - current_margin + margin
            
            # 获取账户资金
            if account_capital is None:
                # 如果没有传入账户资金，使用保证金除以配置的仓位比例来估算
                account_capital = margin / self.trading_config.MAX_POSITION_SIZE
                logger.debug(f"使用估算账户资金: {account_capital:.2f}")
            
            # 计算最大允许保证金（5%）
            max_margin = account_capital * self.trading_config.MAX_POSITION_SIZE
            
            # 检查是否超过最大保证金限制
            if total_margin_after > max_margin:
                logger.warning(f"保证金超过限制: {symbol}, 当前总保证金: {total_margin_used:.4f}, 当前交易对保证金: {current_margin:.4f}, 新增保证金: {margin:.4f}, 总计: {total_margin_after:.4f}, 最大允许: {max_margin:.4f}")
                return False
            
            logger.info(f"风险检查通过: {symbol}, 账户资金: {account_capital:.2f}, 当前总保证金: {total_margin_used:.4f}, 新增保证金: {margin:.4f}, 总计: {total_margin_after:.4f}, 最大允许: {max_margin:.4f}")
            return True
        except Exception as e:
            logger.error(f"验证仓位失败: {e}")
            return False
    
    def check_order_risk(self, symbol: str, side: str, quantity: float,
                        price: float, current_price: float = None, 
                        account_capital: float = None) -> RiskCheckResult:
        self.reset_daily_metrics()

        if current_price is None:
            current_price = price

        violations = []
        warnings = []
        risk_score = 0.0

        # 【修复】使用保证金而不是持仓价值进行比较
        # 计算所有持仓的总保证金（而不仅仅是当前交易对的保证金）
        total_margin_used = sum(pos.get('margin', 0.0) for pos in self.positions.values())
        
        # 计算当前交易对已占用的保证金
        current_margin = self.positions.get(symbol, {}).get('margin', 0.0)
        
        # 计算本次订单需要的保证金 = 持仓价值 / 杠杆
        position_value = quantity * current_price
        margin_needed = position_value / self.trading_config.LEVERAGE
        
        # 如果当前交易对已有持仓，需要减去当前持仓的保证金，再加上新的保证金
        # 如果当前交易对没有持仓，直接加上新的保证金
        if side == 'buy':
            total_margin_after = total_margin_used - current_margin + margin_needed
        else:
            # 平仓时，保证金会减少
            total_margin_after = total_margin_used - current_margin

        # 计算最大允许保证金（基于账户资金的5%）
        if account_capital and account_capital > 0:
            max_margin = account_capital * self.trading_config.MAX_POSITION_SIZE
            logger.debug(f"风控检查: 账户资金={account_capital:.2f}, 最大允许保证金={max_margin:.4f} (5%)")
        else:
            # # 如果没有账户资金信息，基于本次保证金反推账户资金
            # estimated_capital = margin_needed / self.trading_config.MAX_POSITION_SIZE if self.trading_config.MAX_POSITION_SIZE > 0 else margin_needed
            # max_margin = estimated_capital * self.trading_config.MAX_POSITION_SIZE
            logger.warning(f"风控检查: 未获取到账户资金，请先充值")

        if total_margin_after > max_margin:
            excess = total_margin_after - max_margin
            violations.append(f"保证金超过限制: 超出 {excess:.4f} (当前总保证金: {total_margin_used:.4f}, 当前交易对保证金: {current_margin:.4f}, 新增: {margin_needed:.4f}, 总计: {total_margin_after:.4f}, 最大: {max_margin:.4f})")
            risk_score += 30
        else:
            logger.debug(f"风控检查通过: 当前总保证金={total_margin_used:.4f}, 新增={margin_needed:.4f}, 总计={total_margin_after:.4f}, 最大={max_margin:.4f}")

        if self.daily_pnl < 0 and abs(self.daily_pnl) > self.daily_loss_limit:
            violations.append(f"日度亏损已达限制: {self.daily_pnl:.4f}")
            risk_score += 25

        if self.current_drawdown > self.max_drawdown_limit * 0.8:
            warnings.append(f"当前回撤较高: {self.current_drawdown:.2%}")
            risk_score += 15

        suggested_qty = quantity
        stop_loss_price = 0.0
        take_profit_price = 0.0

        if self.trading_config.ENABLE_STOP_LOSS:
            if side == 'buy':
                stop_loss_price = current_price * (1 - self.trading_config.STOP_LOSS_PERCENT)
                take_profit_price = current_price * (1 + self.trading_config.TAKE_PROFIT_PERCENT)
            else:
                stop_loss_price = current_price * (1 + self.trading_config.STOP_LOSS_PERCENT)
                take_profit_price = current_price * (1 - self.trading_config.TAKE_PROFIT_PERCENT)

        if side == 'buy' and current_price < stop_loss_price:
            violations.append("止损价高于当前价格")
            risk_score += 20

        approved = len(violations) == 0

        if not approved:
            self._record_risk_event('order_rejected', {
                'symbol': symbol,
                'violations': violations,
                'risk_score': risk_score
            })
        elif warnings:
            self._record_risk_event('risk_warning', {
                'symbol': symbol,
                'warnings': warnings,
                'risk_score': risk_score
            })

        return RiskCheckResult(

            approved=approved,
            risk_score=risk_score,
            violations=violations,
            warnings=warnings,
            max_position_size=self.trading_config.MAX_POSITION_SIZE,
            suggested_quantity=suggested_qty,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price
        )

    def update_position(self, symbol: str, side: str, quantity: float, price: float):
        if symbol not in self.positions:
            self.positions[symbol] = {'quantity': 0, 'avg_price': 0, 'value': 0, 'margin': 0.0}

        pos = self.positions[symbol]

        if side == 'buy':
            total_qty = pos['quantity'] + quantity
            new_avg = (pos['quantity'] * pos['avg_price'] + quantity * price) / total_qty if total_qty > 0 else price
            pos['quantity'] = total_qty
            pos['avg_price'] = new_avg
            pos['value'] = total_qty * price
            # 【修复】计算保证金 = 持仓价值 / 杠杆
            pos['margin'] = pos['value'] / self.trading_config.LEVERAGE
        else:
            pos['quantity'] = max(0, pos['quantity'] - quantity)
            if pos['quantity'] > 0:
                pos['value'] = pos['quantity'] * price
                # 【修复】更新保证金
                pos['margin'] = pos['value'] / self.trading_config.LEVERAGE
            else:
                pos['avg_price'] = 0
                pos['value'] = 0
                pos['margin'] = 0.0

        self._update_drawdown()

    def close_position(self, symbol: str, exit_price: float, pnl: float):
        if symbol in self.positions:
            del self.positions[symbol]

        self.cumulative_pnl += pnl
        self.daily_pnl += pnl
        self.daily_trade_count += 1
        self.daily_volume += abs(pnl)

        self._update_drawdown()
        self._record_risk_event('position_closed', {'symbol': symbol, 'pnl': pnl})

    def _update_drawdown(self):
        portfolio_value = self._calculate_portfolio_value()

        if portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = portfolio_value

        if self.peak_portfolio_value > 0:
            self.current_drawdown = (self.peak_portfolio_value - portfolio_value) / self.peak_portfolio_value

    def _calculate_portfolio_value(self) -> float:
        return sum(pos['value'] for pos in self.positions.values())

    def get_portfolio_metrics(self) -> Dict:
        portfolio_value = self._calculate_portfolio_value()

        long_exposure = sum(pos['value'] for sym, pos in self.positions.items()
                           if 'USDC' not in sym)
        short_exposure = 0.0

        net_exposure = (long_exposure - short_exposure) / portfolio_value if portfolio_value > 0 else 0
        gross_exposure = (long_exposure + short_exposure) / portfolio_value if portfolio_value > 0 else 0

        return {
            'portfolio_value': portfolio_value,
            'positions_count': len(self.positions),
            'current_drawdown': self.current_drawdown,
            'daily_pnl': self.daily_pnl,
            'daily_trades': self.daily_trade_count,
            'net_exposure': net_exposure,
            'gross_exposure': gross_exposure
        }

    def _record_risk_event(self, event_type: str, data: Dict):
        event = {
            'timestamp': datetime.now(),
            'type': event_type,
            'data': data
        }
        self.risk_events.append(event)
        
        # 保存到数据库
        if self.db_manager:
            try:
                description = f"{event_type}: {str(data)}"
                severity = 'medium'
                if 'violations' in data or 'risk_score' in data and data['risk_score'] > 50:
                    severity = 'high'
                
                self.db_manager.save_risk_event(
                    event_type=event_type,
                    severity=severity,
                    description=description,
                    affected_symbols=data.get('symbol')
                )
            except Exception as e:
                logger.error(f"保存风险事件到数据库失败: {e}")

        if len(self.risk_events) > 1000:

            self.risk_events = self.risk_events[-500:]

    def calculate_var_historical(self, returns: np.ndarray, confidence: float = 0.95,
                                  horizon: int = 1) -> VaRResult:
        if len(returns) < 30:
            logger.warning("历史数据不足，使用简化VaR计算")
            return self._simplified_var_calculation(confidence, horizon)

        var_95 = np.percentile(returns, (1 - 0.95) * 100) * np.sqrt(horizon)
        var_99 = np.percentile(returns, (1 - 0.99) * 100) * np.sqrt(horizon)

        es_95 = returns[returns <= var_95].mean() * np.sqrt(horizon) if len(returns[returns <= var_95]) > 0 else var_95
        es_99 = returns[returns <= var_99].mean() * np.sqrt(horizon) if len(returns[returns <= var_99]) > 0 else var_99

        return VaRResult(
            var_95=float(var_95),
            var_99=float(var_99),
            expected_shortfall_95=float(es_95),
            expected_shortfall_99=float(es_99),
            confidence_level=confidence,
            horizon_days=horizon
        )

    def calculate_var_parametric(self, returns: np.ndarray, confidence: float = 0.95,
                                  horizon: int = 1) -> VaRResult:
        if len(returns) < 30:
            return self._simplified_var_calculation(confidence, horizon)

        mu = np.mean(returns)
        sigma = np.std(returns)

        z_score = stats.norm.ppf(1 - confidence)

        var_95 = -(mu * horizon + z_score * sigma * np.sqrt(horizon))
        var_99 = -(mu * horizon + stats.norm.ppf(0.99) * sigma * np.sqrt(horizon))

        es_95 = -(mu * horizon + sigma * np.sqrt(horizon) * stats.norm.pdf(z_score) / (1 - confidence))
        es_99 = -(mu * horizon + sigma * np.sqrt(horizon) * stats.norm.pdf(stats.norm.ppf(0.99)) / 0.01)

        return VaRResult(
            var_95=float(var_95),
            var_99=float(var_99),
            expected_shortfall_95=float(es_95),
            expected_shortfall_99=float(es_99),
            confidence_level=confidence,
            horizon_days=horizon
        )

    def calculate_var_monte_carlo(self, returns: np.ndarray, portfolio_value: float,
                                   confidence: float = 0.95, horizon: int = 1,
                                   simulations: int = 10000) -> VaRResult:
        if len(returns) < 30:
            return self._simplified_var_calculation(confidence, horizon)

        mu = np.mean(returns)
        sigma = np.std(returns)

        random_returns = np.random.normal(mu, sigma, (simulations, horizon))
        portfolio_returns = np.sum(random_returns, axis=1)

        var_95 = -np.percentile(portfolio_returns, (1 - confidence) * 100) * portfolio_value
        var_99 = -np.percentile(portfolio_returns, (1 - 0.99) * 100) * portfolio_value

        es_95 = -portfolio_returns[portfolio_returns <= -var_95 / portfolio_value].mean() * portfolio_value
        es_99 = -portfolio_returns[portfolio_returns <= -var_99 / portfolio_value].mean() * portfolio_value

        return VaRResult(
            var_95=float(var_95),
            var_99=float(var_99),
            expected_shortfall_95=float(es_95),
            expected_shortfall_99=float(es_99),
            confidence_level=confidence,
            horizon_days=horizon
        )

    def _simplified_var_calculation(self, confidence: float, horizon: int) -> VaRResult:
        base_var = 0.02
        var_95 = base_var * np.sqrt(horizon)
        var_99 = base_var * 1.5 * np.sqrt(horizon)

        return VaRResult(
            var_95=var_95,
            var_99=var_99,
            expected_shortfall_95=var_95 * 1.2,
            expected_shortfall_99=var_99 * 1.2,
            confidence_level=confidence,
            horizon_days=horizon
        )

    def run_stress_test(self, portfolio_value: float, positions: Dict[str, Dict],
                        scenarios: List[Dict] = None) -> List[StressTestResult]:
        if scenarios is None:
            scenarios = self._get_default_scenarios()

        results = []

        for scenario in scenarios:
            scenario_name = scenario.get('name', 'Unknown')
            price_changes = scenario.get('price_changes', {})

            total_impact = 0.0
            position_impacts = {}

            for symbol, pos in positions.items():
                if symbol in price_changes:
                    change = price_changes[symbol]
                    impact = pos.get('value', 0) * change
                    position_impacts[symbol] = impact
                    total_impact += impact
                else:
                    position_impacts[symbol] = 0.0

            impact_pct = total_impact / portfolio_value if portfolio_value > 0 else 0

            if impact_pct > -0.3:
                recovery_time = 1
                risk_rating = "LOW"
            elif impact_pct > -0.5:
                recovery_time = 3
                risk_rating = "MODERATE"
            elif impact_pct > -0.7:
                recovery_time = 6
                risk_rating = "HIGH"
            else:
                recovery_time = 12
                risk_rating = "CRITICAL"

            results.append(StressTestResult(
                scenario_name=scenario_name,
                portfolio_impact=impact_pct,
                position_impacts=position_impacts,
                recovery_time_estimate=recovery_time,
                risk_rating=risk_rating
            ))

            logger.info(f"压力测试 - {scenario_name}: 影响 {impact_pct:.2%}, 风险评级 {risk_rating}")

        return results

    def _get_default_scenarios(self) -> List[Dict]:
        return [
            {
                'name': '市场崩盘',
                'price_changes': {
                    'BTC_USDC': -0.30,
                    'ETH_USDC': -0.35,
                    'SOL_USDC': -0.40
                }
            },
            {
                'name': '流动性危机',
                'price_changes': {
                    'BTC_USDC': -0.20,
                    'ETH_USDC': -0.25,
                    'SOL_USDC': -0.30,
                    'SOL_USDC': -0.15
                }
            },
            {
                'name': '单币种剧烈波动',
                'price_changes': {
                    'SOL_USDC': -0.50
                }
            },
            {
                'name': '监管黑天鹅',
                'price_changes': {
                    'BTC_USDC': -0.25,
                    'ETH_USDC': -0.40,
                    'SOL_USDC': -0.45
                }
            }
        ]

    def generate_risk_report(self, returns: np.ndarray = None,
                             portfolio_value: float = 0.0) -> Dict:
        metrics = self.get_portfolio_metrics()

        var_result = None
        if returns is not None and len(returns) >= 30:
            var_result = self.calculate_var_historical(returns)

        stress_results = self.run_stress_test(
            portfolio_value or metrics['portfolio_value'],
            self.positions
        )

        risk_score = min(100, metrics['current_drawdown'] * 200 +
                        abs(metrics['daily_pnl']) * 50 +
                        len(self.risk_events) * 2)

        report = {
            'timestamp': datetime.now().isoformat(),
            'portfolio_metrics': metrics,
            'var_metrics': {
                'var_95': var_result.var_95 if var_result else 0,
                'var_99': var_result.var_99 if var_result else 0,
                'expected_shortfall_95': var_result.expected_shortfall_95 if var_result else 0
            },
            'stress_test_results': [
                {
                    'scenario': r.scenario_name,
                    'impact': r.portfolio_impact,
                    'risk_rating': r.risk_rating,
                    'recovery_days': r.recovery_time_estimate
                }
                for r in stress_results
            ],
            'risk_score': risk_score,
            'risk_level': 'LOW' if risk_score < 30 else 'MEDIUM' if risk_score < 60 else 'HIGH',
            'recommendations': self._generate_risk_recommendations(metrics, var_result)
        }

        return report

    def _generate_risk_recommendations(self, metrics: Dict, var_result: VaRResult) -> List[str]:
        recommendations = []

        if metrics['current_drawdown'] > 0.1:
            recommendations.append("建议降低仓位，减少风险暴露")

        if metrics['daily_pnl'] < 0 and abs(metrics['daily_pnl']) > metrics['portfolio_value'] * 0.02:
            recommendations.append("日度亏损较大，建议暂停新开仓位")

        if len(self.positions) > 5:
            recommendations.append("持仓过于分散，建议集中于核心资产")

        if var_result and var_result.var_95 < -0.05:
            recommendations.append("VaR显示潜在损失风险较高，建议增加止损幅度")

        if not recommendations:
            recommendations.append("当前风险水平可控，继续监控")

        return recommendations

    def update_monitoring(self):
        self.reset_daily_metrics()
