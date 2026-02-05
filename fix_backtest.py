# 修复回测引擎：添加多空双向持仓支持
import re

file_path = 'backpack_quant_trading/engine/backtest.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改positions类型注解
content = re.sub(
    r'self\.positions: Dict\[str, float\] = \{\}',
    'self.positions: Dict[str, Dict] = {}  # 双向持仓: {symbol: {long: {...}, short: {...}}}',
    content
)

# 2. 替换_execute_trade方法
old_execute_trade = r'''    def _execute_trade\(self, signal, current_date\):
        """执行交易"""
        if signal\.action == 'buy':
            self\._execute_buy\(signal, current_date\)
        elif signal\.action == 'sell':
            self\._execute_sell\(signal, current_date\)'''

new_execute_trade = '''    def _execute_trade(self, signal, current_date):
        """执行交易（支持多空双向持仓）"""
        symbol = signal.symbol
        action = signal.action
        price = float(signal.price) if signal.price else 0
        quantity = float(signal.quantity) if signal.quantity else 0
        
        # 初始化持仓
        if symbol not in self.positions:
            self.positions[symbol] = {
                'long': {'qty': 0, 'entry_price': 0, 'margin': 0},
                'short': {'qty': 0, 'entry_price': 0, 'margin': 0}
            }
        
        pos = self.positions[symbol]
        
        # BUY: 有空仓则平空，否则开多
        if action == 'buy':
            if pos['short']['qty'] > 0:
                self._close_short(symbol, quantity, price, current_date, signal.reason)
            else:
                self._open_long(symbol, quantity, price, current_date, signal.reason)
        # SELL: 有多仓则平多，否则开空
        elif action == 'sell':
            if pos['long']['qty'] > 0:
                self._close_long(symbol, quantity, price, current_date, signal.reason)
            else:
                self._open_short(symbol, quantity, price, current_date, signal.reason)'''

content = re.sub(old_execute_trade, new_execute_trade, content, flags=re.DOTALL)

# 3. 删除旧的buy/sell方法，添加新的开平仓方法
old_methods = r'    def _execute_buy\(self.*?(?=\n    def calculate_metrics)'

new_methods = '''    def _open_long(self, symbol: str, quantity: float, price: float, current_date, reason: str):
        """开多仓"""
        actual_price = price * (1 + self.slippage)
        leverage = 100
        margin = (actual_price * quantity) / leverage
        commission = margin * self.commission_rate
        trade_value = margin + commission
        
        if trade_value > self.capital:
            logger.warning(f"资金不足，无法开多")
            return
        
        self.positions[symbol]['long'] = {'qty': quantity, 'entry_price': actual_price, 'margin': margin}
        self.capital -= trade_value
        
        self.trades.append(Trade(
            symbol=symbol, action='buy', quantity=quantity, entry_price=actual_price,
            entry_time=current_date, commission=commission, reason=reason
        ))
        logger.info(f"开多 {symbol}: {quantity:.4f} @ {actual_price:.2f}")
    
    def _open_short(self, symbol: str, quantity: float, price: float, current_date, reason: str):
        """开空仓"""
        actual_price = price * (1 - self.slippage)
        leverage = 100
        margin = (actual_price * quantity) / leverage
        commission = margin * self.commission_rate
        trade_value = margin + commission
        
        if trade_value > self.capital:
            logger.warning(f"资金不足，无法开空")
            return
        
        self.positions[symbol]['short'] = {'qty': quantity, 'entry_price': actual_price, 'margin': margin}
        self.capital -= trade_value
        
        self.trades.append(Trade(
            symbol=symbol, action='sell', quantity=quantity, entry_price=actual_price,
            entry_time=current_date, commission=commission, reason=reason
        ))
        logger.info(f"开空 {symbol}: {quantity:.4f} @ {actual_price:.2f}")
    
    def _close_long(self, symbol: str, quantity: float, price: float, current_date, reason: str):
        """平多仓"""
        pos = self.positions[symbol]['long']
        if pos['qty'] <= 0:
            return
        
        actual_price = price * (1 - self.slippage)
        leverage = 100
        price_change = (actual_price - pos['entry_price']) / pos['entry_price']
        pnl = pos['margin'] * price_change * leverage
        commission = pos['margin'] * self.commission_rate
        final_pnl = pnl - commission
        
        self.capital += pos['margin'] + final_pnl
        self.positions[symbol]['long'] = {'qty': 0, 'entry_price': 0, 'margin': 0}
        
        self.trades.append(Trade(
            symbol=symbol, action='sell', quantity=pos['qty'],
            entry_price=pos['entry_price'], exit_price=actual_price,
            entry_time=current_date, exit_time=current_date,
            pnl=final_pnl, pnl_percent=(final_pnl/pos['margin'])*100,
            commission=commission, reason=reason
        ))
        logger.info(f"平多 {symbol}: PnL={final_pnl:.2f}")
    
    def _close_short(self, symbol: str, quantity: float, price: float, current_date, reason: str):
        """平空仓"""
        pos = self.positions[symbol]['short']
        if pos['qty'] <= 0:
            return
        
        actual_price = price * (1 + self.slippage)
        leverage = 100
        price_change = (pos['entry_price'] - actual_price) / pos['entry_price']
        pnl = pos['margin'] * price_change * leverage
        commission = pos['margin'] * self.commission_rate
        final_pnl = pnl - commission
        
        self.capital += pos['margin'] + final_pnl
        self.positions[symbol]['short'] = {'qty': 0, 'entry_price': 0, 'margin': 0}
        
        self.trades.append(Trade(
            symbol=symbol, action='buy', quantity=pos['qty'],
            entry_price=pos['entry_price'], exit_price=actual_price,
            entry_time=current_date, exit_time=current_date,
            pnl=final_pnl, pnl_percent=(final_pnl/pos['margin'])*100,
            commission=commission, reason=reason
        ))
        logger.info(f"平空 {symbol}: PnL={final_pnl:.2f}")

'''

content = re.sub(old_methods, new_methods, content, flags=re.DOTALL)

# 保存
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ 回测引擎修复完成")
