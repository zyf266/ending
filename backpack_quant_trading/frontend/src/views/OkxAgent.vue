<template>
  <div class="page okx-agent-page">
    <div class="hero">
      <div class="hero-badge">OKX 官方 · 开源 MIT</div>
      <h1>OKX Agent Trade Kit</h1>
      <p class="hero-desc">{{ capabilities?.subtitle || '欧易官方 AI 智能交易工具包 · 自然语言驱动' }}</p>
      <p class="hero-detail">{{ capabilities?.description || '将 AI 与 OKX 账户直接连接，用自然语言执行行情、现货/合约/期权交易与网格策略。' }}</p>
    </div>

    <el-tabs v-model="activeTab" class="main-tabs">
      <el-tab-pane label="能力概览" name="capabilities">
        <div class="section">
          <h3>核心功能</h3>
          <ul class="feature-list">
            <li v-for="(f, i) in (capabilities?.features || [])" :key="i">{{ f }}</li>
          </ul>
        </div>
        <div class="section">
          <h3>使用方式</h3>
          <div class="mode-cards">
            <div v-for="m in (capabilities?.usage_modes || [])" :key="m.id" class="mode-card">
              <span class="mode-tag">{{ m.id.toUpperCase() }}</span>
              <h4>{{ m.name }}</h4>
              <code>{{ m.pkg }}</code>
              <p>{{ m.desc }}</p>
            </div>
          </div>
        </div>
        <div class="section">
          <h3>功能模块</h3>
          <div class="module-grid">
            <el-card v-for="mod in (capabilities?.modules || [])" :key="mod.id" class="module-card" shadow="hover">
              <template #header>
                <span class="module-name">{{ mod.name }}</span>
                <el-tag size="small" :type="mod.auth.includes('公开') ? 'success' : 'warning'">{{ mod.auth }}</el-tag>
              </template>
              <p class="module-desc">{{ mod.description }}</p>
              <div class="tool-tags">
                <el-tag v-for="t in (mod.tools || []).slice(0, 4)" :key="t.name" size="small" class="tool-tag">{{ t.name }}</el-tag>
                <span v-if="(mod.tools || []).length > 4" class="more">+{{ mod.tool_count - 4 }} 更多</span>
              </div>
            </el-card>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="快速开始" name="quickstart">
        <div class="section" v-if="quickstart">
          <h3>OpenClaw（Skills）</h3>
          <div v-for="s in quickstart.openclaw" :key="'oc-' + s.step" class="step-block">
            <span class="step-num">Step {{ s.step }}</span>
            <strong>{{ s.title }}</strong>
            <p>{{ s.content }}</p>
          </div>
          <h3>MCP 客户端（Cursor / Claude / VS Code）</h3>
          <div v-for="s in quickstart.mcp" :key="'mcp-' + s.step" class="step-block">
            <span class="step-num">Step {{ s.step }}</span>
            <strong>{{ s.title }}</strong>
            <p>{{ s.content }}</p>
          </div>
          <h3>配置文件示例（~/.okx/config.toml）</h3>
          <pre class="code-block">{{ quickstart.config_example }}</pre>
          <p class="hint">⚠️ 切勿将 API Key 粘贴到 AI 对话框，仅保存在本地配置文件。建议使用子账户并开启最小权限。</p>
        </div>
      </el-tab-pane>

      <el-tab-pane label="安全与 FAQ" name="security">
        <div class="section" v-if="capabilities?.security">
          <h3>安全机制</h3>
          <ul class="security-list">
            <li v-for="(s, i) in capabilities.security" :key="i">{{ s }}</li>
          </ul>
        </div>
        <div class="section" v-if="faq?.items">
          <h3>常见问题</h3>
          <el-collapse>
            <el-collapse-item v-for="(item, i) in faq.items" :key="i" :title="item.q" :name="i">
              <p>{{ item.a }}</p>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-tab-pane>

      <el-tab-pane label="相关链接" name="links">
        <div class="section" v-if="capabilities?.links">
          <h3>官方资源</h3>
          <div class="link-grid">
            <a :href="capabilities.links.github_mcp" target="_blank" rel="noopener" class="link-card">GitHub (MCP + CLI)</a>
            <a :href="capabilities.links.github_skills" target="_blank" rel="noopener" class="link-card">GitHub (Skills)</a>
            <a :href="capabilities.links.npm_mcp" target="_blank" rel="noopener" class="link-card">npm: okx-trade-mcp</a>
            <a :href="capabilities.links.npm_cli" target="_blank" rel="noopener" class="link-card">npm: okx-trade-cli</a>
            <a :href="capabilities.links.okx_api_docs" target="_blank" rel="noopener" class="link-card">OKX 开放 API 文档</a>
            <a :href="capabilities.links.telegram" target="_blank" rel="noopener" class="link-card">Telegram 社群</a>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <div class="footer-note">
      本页为「沐龙量化」与 OKX Agent Trade Kit 的集成说明，不存储任何 API 凭证；实际交易与密钥管理均在您本地或 OKX 平台完成。
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getOkxAgentCapabilities, getOkxAgentQuickstart, getOkxAgentFaq } from '../api/okxAgent'

const activeTab = ref('capabilities')
const capabilities = ref(null)
const quickstart = ref(null)
const faq = ref(null)

onMounted(async () => {
  try {
    const [cap, qs, f] = await Promise.all([
      getOkxAgentCapabilities(),
      getOkxAgentQuickstart(),
      getOkxAgentFaq(),
    ])
    capabilities.value = cap
    quickstart.value = qs
    faq.value = f
  } catch (e) {
    capabilities.value = {}
    quickstart.value = { openclaw: [], mcp: [], config_example: '' }
    faq.value = { items: [] }
  }
})
</script>

<style scoped>
.page { max-width: 960px; margin: 0 auto; }
.hero {
  text-align: center;
  padding: 32px 24px 40px;
  margin-bottom: 24px;
  background: linear-gradient(135deg, var(--color-bg-card) 0%, rgba(99, 102, 241, 0.06) 100%);
  border-radius: var(--radius-lg, 12px);
  border: 1px solid var(--color-border);
}
.hero-badge {
  display: inline-block;
  font-size: 12px;
  color: var(--color-primary);
  background: rgba(99, 102, 241, 0.12);
  padding: 4px 12px;
  border-radius: 999px;
  margin-bottom: 16px;
}
.hero h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 8px 0;
  letter-spacing: -0.02em;
}
.hero-desc { font-size: 15px; color: var(--color-text-secondary); margin: 0 0 8px 0; }
.hero-detail { font-size: 14px; color: var(--color-text-muted); margin: 0; max-width: 640px; margin-left: auto; margin-right: auto; }

.main-tabs { margin-bottom: 24px; }
.section { margin-bottom: 32px; }
.section h3 { font-size: 16px; margin-bottom: 12px; color: var(--color-text); }
.feature-list { margin: 0; padding-left: 20px; color: var(--color-text-secondary); line-height: 1.8; }
.mode-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
.mode-card {
  padding: 16px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md, 8px);
}
.mode-tag { font-size: 11px; color: var(--color-primary); font-weight: 600; }
.mode-card h4 { margin: 8px 0 4px 0; font-size: 15px; }
.mode-card code { font-size: 12px; color: var(--color-text-muted); }
.mode-card p { margin: 8px 0 0 0; font-size: 13px; color: var(--color-text-secondary); }

.module-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.module-card :deep(.el-card__header) { display: flex; align-items: center; justify-content: space-between; }
.module-name { font-weight: 600; }
.module-desc { font-size: 13px; color: var(--color-text-secondary); margin-bottom: 12px; }
.tool-tags { margin-right: 6px; }
.more { font-size: 12px; color: var(--color-text-muted); }

.step-block { margin-bottom: 20px; padding: 12px 16px; background: var(--color-bg-card); border-radius: 8px; border-left: 3px solid var(--color-primary); }
.step-num { font-size: 11px; color: var(--color-primary); font-weight: 600; }
.step-block strong { display: block; margin: 4px 0 8px 0; }
.step-block p { margin: 0; font-size: 14px; color: var(--color-text-secondary); }
.code-block {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 8px;
  font-size: 13px;
  overflow-x: auto;
  margin: 12px 0;
}
.hint { font-size: 13px; color: var(--color-text-muted); margin-top: 12px; }

.security-list { margin: 0; padding-left: 20px; line-height: 1.9; color: var(--color-text-secondary); }
.link-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
.link-card {
  display: block;
  padding: 14px 16px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  color: var(--color-primary);
  text-decoration: none;
  font-size: 14px;
  transition: background 0.2s, border-color 0.2s;
}
.link-card:hover { background: rgba(99, 102, 241, 0.08); border-color: var(--color-primary); }

.footer-note {
  font-size: 12px;
  color: var(--color-text-muted);
  text-align: center;
  padding: 24px 16px;
  border-top: 1px solid var(--color-border);
  margin-top: 24px;
}
</style>
