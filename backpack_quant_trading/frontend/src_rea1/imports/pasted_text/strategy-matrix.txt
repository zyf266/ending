<template>
  <div class="page strategy-matrix-alt">
    <div class="title-row">
      <h2>量化策略矩阵</h2>
    </div>

    <div class="cards-grid">
      <!-- 三个策略卡片，一行铺满 -->
      <router-link to="/strategies/eth-trend" class="strategy-card">
        <h3 class="card-title">沐龙加密波动率增强策略 (ML-DTS)</h3>
        <div class="card-body">
          <div class="card-left">
            <p class="card-desc">
              专注 BTC / ETH 等主流加密货币，捕捉由波动率扩张驱动的中长期趋势，通过多周期协同过滤震荡噪音，追求稳健的风险调整后收益。
            </p>
          </div>
          <div class="card-right">
            <div class="card-meta">
              <div class="meta-line">
                <span class="meta-icon">📈</span>
                <span class="meta-label">策略盈亏：</span>
                <span class="meta-value highlight">97.74%</span>
              </div>
              <div class="meta-line">
                <span class="meta-icon">🔁</span>
                <span class="meta-label">平均年化：</span>
                <span class="meta-value">22.82%</span>
              </div>
              <div class="meta-line">
                <span class="meta-icon">📉</span>
                <span class="meta-label">本金回撤：</span>
                <span class="meta-value">0%</span>
              </div>
              <div class="meta-line">
                <span class="meta-icon">🧮</span>
                <span class="meta-label">盈利因子：</span>
                <span class="meta-value">1.506</span>
              </div>
            </div>
          </div>
        </div>
      </router-link>

      <router-link to="/strategies/paxg-trend" class="strategy-card">
        <h3 class="card-title">沐龙黄金波动率周期捕捉策略 (ML-GVCS)</h3>
        <div class="card-body">
          <div class="card-left">
            <p class="card-desc">
              专注 XAU/USD 波动率周期，结合宏观趋势与关键支撑区间布局，坚持「低位等待、确定性介入」原则，利用波动率扩张捕捉中期行情。
            </p>
          </div>
          <div class="card-right">
            <div class="card-meta">
              <div class="meta-line">
                <span class="meta-icon">📈</span>
                <span class="meta-label">策略盈亏：</span>
                <span class="meta-value highlight">79.81%</span>
              </div>
              <div class="meta-line">
                <span class="meta-icon">🔁</span>
                <span class="meta-label">平均年化：</span>
                <span class="meta-value">36.44%</span>
              </div>
              <div class="meta-line">
                <span class="meta-icon">📉</span>
                <span class="meta-label">本金回撤：</span>
                <span class="meta-value">-1.81%</span>
              </div>
              <div class="meta-line">
                <span class="meta-icon">🧮</span>
                <span class="meta-label">盈利因子：</span>
                <span class="meta-value">2.887</span>
              </div>
            </div>
          </div>
        </div>
      </router-link>

      <router-link to="/strategies/nas100-trend" class="strategy-card">
        <h3 class="card-title">沐龙纳指趋势追踪增强策略 (ML-NAS)</h3>
        <div class="card-body">
          <div class="card-left">
            <p class="card-desc">
              聚焦纳斯达克指数的中长期趋势行情，结合趋势强度与回撤过滤，围绕关键趋势段进行分批建仓与风控，强调顺势持有与风险控制。
            </p>
          </div>
          <div class="card-right">
            <div class="card-meta">
              <div class="meta-line">
                <span class="meta-icon">📈</span>
                <span class="meta-label">策略盈亏：</span>
                <span class="meta-value highlight">60.11%</span>
              </div>
              <div class="meta-line">
                <span class="meta-icon">🔁</span>
                <span class="meta-label">平均年化：</span>
                <span class="meta-value">27.44%</span>
              </div>
              <div class="meta-line">
                <span class="meta-icon">📉</span>
                <span class="meta-label">本金回撤：</span>
                <span class="meta-value">0%</span>
              </div>
              <div class="meta-line">
                <span class="meta-icon">🧮</span>
                <span class="meta-label">盈利因子：</span>
                <span class="meta-value">1.653</span>
              </div>
            </div>
          </div>
        </div>
      </router-link>
    </div>
  </div>
</template>

<script setup>
</script>

<style scoped>
.strategy-matrix-alt {
  margin: 0; /* 和其它视图一致，从左上开始铺开 */
}

.title-row {
  margin-bottom: 32px;
  padding-left: 12px;
  border-left: 4px solid var(--color-primary);
}

.title-row h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text);
}

.title-row .sub {
  margin: 6px 0 0 0;
  font-size: 14px;
  color: var(--color-text-muted);
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)); /* 一行三个等宽卡片，从左到右铺满 */
  column-gap: 30px;
  row-gap: 32px;
  align-items: stretch;
}

.strategy-card {
  display: block;
  padding: 24px 24px 20px;
  border-radius: var(--radius-lg, 14px);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  text-decoration: none;
  color: inherit;
  box-shadow: var(--shadow-sm);
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
  /* 去掉固定高度，让内容自然决定高度，减少底部留白 */
}

.strategy-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-primary);
  box-shadow: 0 6px 18px rgba(99, 102, 241, 0.18);
}

.card-title {
  margin: 0 0 12px 0;
  font-size: 19px;
  font-weight: 700;
}

.card-body {
  display: flex;
  gap: 18px;
  align-items: stretch;
}

.card-left {
  flex: 1.2;
}

.card-right {
  flex: 1;
  border-radius: 12px;
  padding: 10px 12px;
  background: radial-gradient(circle at top left, rgba(59, 130, 246, 0.18), transparent 55%),
    radial-gradient(circle at bottom right, rgba(16, 185, 129, 0.14), transparent 55%),
    rgba(15, 23, 42, 0.04);
}

.card-desc {
  margin: 0 0 14px 0;
  font-size: 15px;
  color: var(--color-text-muted);
  line-height: 1.6;
}

.card-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 15px;
}

.meta-line {
  display: flex;
  align-items: center;
  gap: 6px;
}

.meta-icon {
  width: 20px;
  text-align: center;
}

.meta-label {
  color: var(--color-text-muted);
}

.meta-value {
  color: var(--color-text);
}

.meta-value.highlight {
  font-weight: 600;
  color: var(--color-success, #16a34a);
}

@media (max-width: 768px) {
  .cards-grid {
    grid-template-columns: 1fr;
  }

  .card-body {
    flex-direction: column;
  }
}
</style>

