<template>
  <div class="chatbot-wrapper" :style="wrapperStyle" ref="wrapperRef">
    <!-- 悬浮头像 - 豆包风格，支持拖拽 -->
    <div
      class="chatbot-avatar"
      :class="{ open: panelOpen, dragging }"
      @mousedown="onAvatarMouseDown"
      @click="onAvatarClick"
      title="拖拽移动 · 点击提问"
    >
      <div class="avatar-inner">
        <span class="avatar-emoji">🤖</span>
      </div>
      <span v-if="!panelOpen" class="avatar-pulse"></span>
    </div>

    <!-- 聊天面板 - 根据头像位置自适应左右显示 -->
    <Transition name="panel">
      <div v-show="panelOpen" class="chatbot-panel" :class="{ 'panel-left': panelOnLeft }">
        <div class="panel-header">
          <span class="panel-title">沐龙小助</span>
          <span class="panel-desc">量化交易 · 随时问答</span>
          <button class="panel-close" @click="panelOpen = false" aria-label="关闭">×</button>
        </div>

        <div class="panel-body">
          <div v-if="messages.length === 0" class="welcome-area">
            <p class="welcome-text">你好～我是沐龙量化助手，有什么可以帮你的？</p>
            <p class="guess-label">猜你想问</p>
            <div class="guess-list">
              <button
                v-for="(q, i) in suggestQuestions"
                :key="i"
                class="guess-item"
                @click="askQuestion(q)"
              >
                {{ q }}
              </button>
            </div>
          </div>

          <div v-else class="messages-area" ref="messagesRef">
            <div
              v-for="(m, i) in messages"
              :key="i"
              :class="['msg-row', m.role === 'user' ? 'user' : 'assistant']"
            >
              <div v-if="m.role === 'assistant'" class="msg-avatar">🤖</div>
              <div class="msg-bubble">
                <div class="msg-content" v-html="formatContent(m.content)"></div>
              </div>
              <div v-if="m.role === 'user'" class="msg-avatar user-avatar">我</div>
            </div>
            <div v-if="loading" class="msg-row assistant">
              <div class="msg-avatar">🤖</div>
              <div class="msg-bubble typing">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
              </div>
            </div>
          </div>
        </div>

        <div class="panel-footer">
          <el-input
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            placeholder="输入你的问题..."
            @keydown.enter.exact.prevent="send"
            class="chat-input"
          />
          <el-button type="primary" :loading="loading" @click="send" class="send-btn">
            发送
          </el-button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import { sendChat } from '../api/chat'

const panelOpen = ref(false)
const inputText = ref('')
const messages = ref([])
const loading = ref(false)
const messagesRef = ref(null)
const wrapperRef = ref(null)

// 拖拽：用 left/top 定位，初始在右下角
const pos = ref({ left: null, top: null })
const dragging = ref(false)
const dragStart = ref({ x: 0, y: 0, left: 0, top: 0 })
const didDrag = ref(false)

const wrapperStyle = computed(() => {
  if (pos.value.left != null && pos.value.top != null) {
    return { left: pos.value.left + 'px', top: pos.value.top + 'px', right: 'auto', bottom: 'auto' }
  }
  return { right: '28px', bottom: '28px' }
})

// 头像偏左时，面板显示在头像右侧，避免被遮挡
const panelOnLeft = computed(() => {
  const l = pos.value.left
  if (l == null) return false
  return l < window.innerWidth / 2
})

function ensurePosition() {
  if (pos.value.left != null) return true
  if (!wrapperRef.value) return false
  const rect = wrapperRef.value.getBoundingClientRect()
  pos.value = { left: rect.left, top: rect.top }
  return true
}

function onAvatarMouseDown(e) {
  if (e.button !== 0) return
  if (!ensurePosition()) return
  dragging.value = true
  didDrag.value = false
  dragStart.value = {
    x: e.clientX,
    y: e.clientY,
    left: pos.value.left,
    top: pos.value.top,
  }
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

function onMouseMove(e) {
  if (!dragging.value) return
  const dx = e.clientX - dragStart.value.x
  const dy = e.clientY - dragStart.value.y
  if (Math.abs(dx) > 4 || Math.abs(dy) > 4) didDrag.value = true
  let left = dragStart.value.left + dx
  let top = dragStart.value.top + dy
  const sz = 56
  left = Math.max(0, Math.min(window.innerWidth - sz, left))
  top = Math.max(0, Math.min(window.innerHeight - sz, top))
  pos.value = { left, top }
}

function onMouseUp() {
  dragging.value = false
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
}

function onAvatarClick(e) {
  if (didDrag.value) return
  togglePanel()
}

const suggestQuestions = [
  '分析当前 ETH 15m K 线趋势，并给出买卖提示',
  '如何设置网格策略？',
  'ETH 当前趋势怎么看？',
  '止损止盈怎么设？',
  '网格和马丁有什么区别？',
]

function togglePanel() {
  panelOpen.value = !panelOpen.value
}

function askQuestion(q) {
  inputText.value = q
  send()
}

function formatContent(text) {
  if (!text) return ''
  return text
    .replace(/\n/g, '<br/>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
}

async function send() {
  const text = inputText.value?.trim()
  if (!text || loading.value) return

  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  loading.value = true

  try {
    const history = messages.value.map((m) => ({ role: m.role, content: m.content }))
    const res = await sendChat({ message: text, history })
    messages.value.push({ role: 'assistant', content: res.reply || '暂无回复' })
  } catch (e) {
    const errMsg = e.response?.data?.detail || e.response?.data?.reply || e.message || '请求失败，请检查网络或稍后重试。'
    messages.value.push({
      role: 'assistant',
      content: typeof errMsg === 'string' ? errMsg : '请求失败，请检查网络或稍后重试。',
    })
  } finally {
    loading.value = false
    nextTick(() => scrollToBottom())
  }
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

watch(panelOpen, (v) => {
  if (v) nextTick(() => scrollToBottom())
})
</script>

<style scoped>
.chatbot-wrapper {
  position: fixed;
  bottom: 28px;
  right: 28px;
  z-index: 2147483647;
  isolation: isolate;
}

.chatbot-avatar {
  position: relative;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-accent) 100%);
  box-shadow: 0 4px 16px rgba(245, 158, 11, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  transition: transform 0.2s, box-shadow 0.2s;
  user-select: none;
}

.chatbot-avatar:active {
  cursor: grabbing;
}

.chatbot-avatar.dragging {
  transition: none;
}

.chatbot-avatar:hover:not(.dragging) {
  transform: scale(1.08);
  box-shadow: 0 6px 24px rgba(245, 158, 11, 0.55);
}

.chatbot-avatar.open {
  transform: scale(0.9);
  box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
}

.avatar-inner {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-emoji {
  font-size: 26px;
}

.avatar-pulse {
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 2px solid var(--color-primary);
  opacity: 0.5;
  animation: pulse 1.5s ease-out infinite;
}

@keyframes pulse {
  to {
    transform: scale(1.2);
    opacity: 0;
  }
}

.chatbot-panel {
  position: absolute;
  bottom: 72px;
  right: 0;
  width: 380px;
  max-height: min(520px, 80vh);
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg), 0 0 0 1px var(--color-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chatbot-panel.panel-left {
  right: auto;
  left: 0;
}

.panel-header {
  padding: 14px 18px;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-accent) 100%);
  color: #fff;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.panel-title {
  font-weight: 700;
  font-size: 16px;
}

.panel-desc {
  font-size: 11px;
  opacity: 0.9;
}

.panel-close {
  margin-left: auto;
  width: 28px;
  height: 28px;
  border: none;
  background: rgba(255, 255, 255, 0.25);
  color: #fff;
  border-radius: 8px;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.2s;
}

.panel-close:hover {
  background: rgba(255, 255, 255, 0.4);
}

.panel-body {
  flex: 1;
  min-height: 200px;
  max-height: 360px;
  overflow-y: auto;
  padding: 16px;
}

.welcome-area {
  text-align: center;
}

.welcome-text {
  margin: 0 0 16px 0;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.6;
}

.guess-label {
  margin: 0 0 10px 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.guess-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.guess-item {
  padding: 10px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s;
}

.guess-item:hover {
  border-color: var(--color-primary);
  background: rgba(245, 158, 11, 0.06);
  color: var(--color-primary);
}

.messages-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.msg-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.msg-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-accent) 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.user-avatar {
  font-size: 12px;
  font-weight: 600;
}

.msg-bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
}

.msg-row.assistant .msg-bubble {
  background: #f8fafc;
  border: 1px solid var(--color-border);
  color: var(--color-text);
}

.msg-row.user .msg-bubble {
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-accent) 100%);
  color: #fff;
}

.msg-content :deep(strong) {
  font-weight: 700;
}

.typing {
  display: flex;
  gap: 4px;
  padding: 14px 18px;
}

.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-text-muted);
  animation: typing 1.4s ease-in-out infinite both;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%,
  80%,
  100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  40% {
    transform: scale(1.2);
    opacity: 1;
  }
}

.panel-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--color-border);
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.chat-input {
  flex: 1;
}

.chat-input :deep(.el-textarea__inner) {
  border-radius: var(--radius-md);
  font-size: 13px;
  resize: none;
}

.send-btn {
  flex-shrink: 0;
}

.panel-enter-active,
.panel-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}

.panel-enter-from,
.panel-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.96);
}
</style>
