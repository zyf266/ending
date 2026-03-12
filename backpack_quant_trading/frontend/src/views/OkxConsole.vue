<template>
  <div class="page okx-console-page chat-page">
    <div class="chat-header">
      <h2>OKX 助手</h2>
      <p class="sub">有啥想查的、想下的单，直接跟我说就行</p>
      <div class="opts">
        <el-input v-model="profile" placeholder="profile（可选）" size="small" class="opt" />
        <el-checkbox v-model="demo" label="模拟盘" />
      </div>
    </div>

    <div class="chat-main">
      <div class="messages" ref="messagesEl">
        <template v-for="(msg, i) in messages" :key="msg.id || i">
          <div class="msg-row" :class="msg.role">
            <div class="avatar">{{ msg.role === 'user' ? '你' : 'OKX' }}</div>
            <div class="bubble">
              <div class="content">{{ msg.content }}</div>
              <div v-if="msg.needConfirm && !msg.confirmDone" class="confirm-wrap">
                <el-button type="primary" size="small" :loading="confirmLoading" @click="onConfirm(msg)">确认执行</el-button>
              </div>
            </div>
          </div>
        </template>
        <div v-if="sending" class="msg-row assistant">
          <div class="avatar">OKX</div>
          <div class="bubble"><span class="typing">正在想...</span></div>
        </div>
      </div>

      <div class="input-row">
        <el-input
          v-model="inputText"
          type="textarea"
          :rows="2"
          placeholder="例如：帮我在模拟盘开个 ETH 多单，保证金 3555u，3x 杠杆"
          class="chat-input"
          @keydown.enter.exact.prevent="send"
        />
        <el-button type="primary" :loading="sending" @click="send">发送</el-button>
      </div>
    </div>

    <p class="cred-hint">凭证来自本机 ~/.okx/config.toml，不会把 Key 发到页面上。</p>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { runAgent as apiRunAgent } from '../api/okxConsole'

const profile = ref('')
const demo = ref(true)
const inputText = ref('')
const sending = ref(false)
const confirmLoading = ref(false)
const messagesEl = ref(null)

const messages = ref([])
let idSeq = 0
function nextId() {
  return 'msg-' + (++idSeq)
}

function appendUser(content) {
  messages.value.push({ id: nextId(), role: 'user', content: (content || '').trim() })
}
function appendAssistant(payload, userText = '') {
  const id = nextId()
  messages.value.push({
    id,
    role: 'assistant',
    content: payload.reply || payload.message || '好的，收到。',
    needConfirm: payload.need_confirm === true,
    confirmDone: false,
    pendingUserText: userText,
  })
  return id
}
function updateLastAssistant(updates) {
  const last = messages.value.filter(m => m.role === 'assistant').pop()
  if (last) Object.assign(last, updates)
}

async function send() {
  const text = (inputText.value || '').trim()
  if (!text || sending.value) return
  inputText.value = ''
  appendUser(text)
  scrollToBottom()
  sending.value = true
  try {
    const res = await apiRunAgent({
      text,
      auto_execute: true,
      confirm: false,
      profile: profile.value || null,
      demo: demo.value,
      json_out: false,
    })
    if (!res.ok) {
      appendAssistant({ reply: res.reply || res.message || '出了点问题，稍后再试吧。' }, text)
    } else {
      appendAssistant({
        reply: res.reply || res.message || '好的，收到。',
        need_confirm: res.need_confirm,
      }, text)
    }
  } catch (e) {
    const status = e.response?.status
    const msg = e.response?.data?.detail || e.message
    if (status === 401) appendAssistant({ reply: '需要先登录一下才能用哦～' })
    else appendAssistant({ reply: msg || '网络或服务异常，稍后再试吧。' })
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

async function onConfirm(msg) {
  const text = msg.pendingUserText || ''
  if (!text) return
  msg.confirmDone = true
  msg.needConfirm = false
  confirmLoading.value = true
  try {
    const res = await apiRunAgent({
      text,
      auto_execute: true,
      confirm: true,
      profile: profile.value || null,
      demo: demo.value,
      json_out: false,
    })
    const reply = res.reply || res.message || (res.ok ? '已经帮你执行啦。' : '执行时出了点问题。')
    msg.content = msg.content ? msg.content + '\n\n' + reply : reply
    if (!res.ok && res.message) msg.content += '\n' + res.message
  } catch (e) {
    msg.content += '\n\n' + (e.response?.data?.detail || e.message || '确认执行失败，稍后再试。')
  } finally {
    confirmLoading.value = false
    scrollToBottom()
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
}
</script>

<style scoped>
.okx-console-page.chat-page { max-width: 720px; margin: 0 auto; min-height: 80vh; display: flex; flex-direction: column; }
.chat-header { margin-bottom: 16px; }
.chat-header h2 { margin: 0; font-size: 22px; font-weight: 700; color: var(--color-text); }
.sub { margin: 6px 0 0 0; font-size: 13px; color: var(--color-text-muted); }
.opts { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.opt { width: 160px; }

.chat-main { flex: 1; display: flex; flex-direction: column; min-height: 400px; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-bg-card); overflow: hidden; }
.messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; min-height: 280px; }
.msg-row { display: flex; gap: 12px; align-items: flex-start; }
.msg-row.user { flex-direction: row-reverse; }
.avatar {
  flex-shrink: 0;
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 600;
  background: var(--color-bg);
  color: var(--color-text-muted);
}
.msg-row.user .avatar { background: var(--color-primary); color: #fff; }
.bubble {
  max-width: 85%;
  padding: 12px 16px;
  border-radius: 14px;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
}
.msg-row.user .bubble { background: rgba(99, 102, 241, 0.15); border-color: rgba(99, 102, 241, 0.35); }
.content { white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.55; color: var(--color-text); }
.confirm-wrap { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--color-border); }
.typing { color: var(--color-text-muted); font-size: 13px; }

.input-row { display: flex; gap: 10px; align-items: flex-end; padding: 12px 16px; border-top: 1px solid var(--color-border); background: var(--color-bg); }
.chat-input { flex: 1; }
.chat-input :deep(textarea) { resize: none; }

.cred-hint { margin-top: 12px; font-size: 12px; color: var(--color-text-muted); text-align: center; }
</style>
