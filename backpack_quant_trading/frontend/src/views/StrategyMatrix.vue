<template>
  <div class="page strategy-matrix-page">
    <div class="title-row">
      <h2>量化策略矩阵</h2>
      <p class="sub">选择策略进入回测看板</p>
    </div>
    <div class="cards-column">
      <router-link to="/strategies/eth-trend" class="strategy-card eth-card">
        <div class="card-title">沐龙加密波动率增强策略 (ML-DTS)</div>
        <div class="card-img-wrap">
          <img :src="cryptoBg" alt="" class="card-img" />
        </div>
      </router-link>
      <router-link to="/strategies/paxg-trend" class="strategy-card gold-card">
        <div class="card-title">沐龙黄金波动率周期捕捉策略 (ML-GVCS)</div>
        <div class="card-img-wrap">
          <img :src="goldBg" alt="" class="card-img" />
        </div>
      </router-link>
      <router-link to="/strategies/nas100-trend" class="strategy-card nas-card">
        <div class="card-title">沐龙纳指趋势追踪增强策略 (ML-NAS)</div>
        <div class="card-img-wrap">
          <img :src="nasBg" alt="" class="card-img" />
        </div>
      </router-link>
    </div>
  </div>
</template>

<script setup>
import cryptoBg from '../assets/加密收益率-无上栏.png'
import goldBg from '../assets/黄金收益图-无上栏.png'
import nasBg from '../assets/纳指收益图-无上栏.png'
</script>

<style scoped>
.strategy-matrix-page { margin: 0; }
.title-row { margin-bottom: 28px; padding-left: 12px; border-left: 4px solid var(--color-primary); }
.title-row h2 { margin: 0; font-size: 22px; font-weight: 700; color: var(--color-text); }
.title-row .sub { margin: 6px 0 0 0; font-size: 14px; color: var(--color-text-muted); }
.cards-column { display: flex; flex-direction: column; gap: 20px; }
.strategy-card {
  display: block;
  border-radius: var(--radius-lg, 12px);
  text-decoration: none;
  color: inherit;
}
.strategy-card:hover {
  transform: translateY(-2px);
}
.card-img-wrap {
  width: 90%;
  margin: 8px auto 0;
  overflow: hidden;
  border-radius: var(--radius-lg, 12px);
  box-shadow: var(--shadow-sm);
}
.card-img {
  display: block;
  width: 100%;
  height: auto; /* 按原图比例完整展示 */
  margin: 0;
}
.gold-card .card-img,
.nas-card .card-img {
  margin-top: -55px; /* 只对黄金/纳指略微裁掉“股权图表”文字区域 */
}
.card-title {
  display: inline-block;
  margin-left: 5%;
  padding: 4px 12px;
  border-radius: 999px;
  background: #4b5563;
  color: #f9fafb;
  font-size: 16px;
  font-weight: 700;
}

</style>
