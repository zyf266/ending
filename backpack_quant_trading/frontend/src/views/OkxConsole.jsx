import React, { useRef, useState } from 'react'
import { runAgent as apiRunAgent } from '../api/okxConsole'
import './OkxConsole.css'

let idSeq = 0
const nextId = () => 'msg-' + (++idSeq)

const OkxConsole = () => {
  const [profile, setProfile] = useState('')
  const [demo, setDemo] = useState(true)
  const [inputText, setInputText] = useState('')
  const [sending, setSending] = useState(false)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [messages, setMessages] = useState([])
  const messagesEl = useRef(null)

  const scrollToBottom = () => {
    setTimeout(() => {
      if (messagesEl.current) messagesEl.current.scrollTop = messagesEl.current.scrollHeight
    }, 0)
  }

  const send = async () => {
    const text = (inputText || '').trim()
    if (!text || sending) return
    setInputText('')
    setMessages((prev) => [...prev, { id: nextId(), role: 'user', content: text }])
    scrollToBottom()
    setSending(true)
    try {
      const res = await apiRunAgent({
        text,
        auto_execute: true,
        confirm: false,
        profile: profile || null,
        demo,
        json_out: false,
      })
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: 'assistant',
          content: res.reply || res.message || (res.ok ? '好的，收到。' : '出了点问题，稍后再试吧。'),
          needConfirm: res.need_confirm === true,
          confirmDone: false,
          pendingUserText: text,
        },
      ])
    } catch (e) {
      const status = e?.response?.status
      const msg = e?.response?.data?.detail || e?.message
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: 'assistant',
          content: status === 401 ? '需要先登录一下才能用哦～' : (msg || '网络或服务异常，稍后再试吧。'),
        },
      ])
    } finally {
      setSending(false)
      scrollToBottom()
    }
  }

  const onConfirm = async (msg) => {
    const text = msg.pendingUserText || ''
    if (!text) return
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msg.id ? { ...m, confirmDone: true, needConfirm: false } : m
      )
    )
    setConfirmLoading(true)
    try {
      const res = await apiRunAgent({
        text,
        auto_execute: true,
        confirm: true,
        profile: profile || null,
        demo,
        json_out: false,
      })
      const reply = res.reply || res.message || (res.ok ? '已经帮你执行啦。' : '执行时出了点问题。')
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msg.id
            ? { ...m, content: (m.content ? m.content + '\n\n' : '') + reply }
            : m
        )
      )
      if (!res.ok && res.message) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msg.id ? { ...m, content: m.content + '\n' + res.message } : m
          )
        )
      }
    } catch (e) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msg.id
            ? { ...m, content: m.content + '\n\n' + (e?.response?.data?.detail || e?.message || '确认执行失败，稍后再试。') }
            : m
        )
      )
    } finally {
      setConfirmLoading(false)
      scrollToBottom()
    }
  }

  return (
    <div className="page okx-console-page chat-page">
      <div className="chat-header">
        <h2>OKX 助手</h2>
        <p className="sub">有啥想查的、想下的单，直接跟我说就行</p>
        <div className="opts">
          <input
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            placeholder="profile（可选）"
            className="opt"
          />
          <label className="checkbox-label">
            <input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} />
            模拟盘
          </label>
        </div>
      </div>

      <div className="chat-main">
        <div className="messages" ref={messagesEl}>
          {messages.map((msg) => (
            <div key={msg.id} className={`msg-row ${msg.role}`}>
              <div className="avatar">{msg.role === 'user' ? '你' : 'OKX'}</div>
              <div className="bubble">
                <div className="content">{msg.content}</div>
                {msg.needConfirm && !msg.confirmDone && (
                  <div className="confirm-wrap">
                    <button
                      type="button"
                      className="btn-primary-sm"
                      disabled={confirmLoading}
                      onClick={() => onConfirm(msg)}
                    >
                      {confirmLoading ? '执行中...' : '确认执行'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
          {sending && (
            <div className="msg-row assistant">
              <div className="avatar">OKX</div>
              <div className="bubble">
                <span className="typing">正在想...</span>
              </div>
            </div>
          )}
        </div>

        <div className="input-row">
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            rows={2}
            placeholder="例如：帮我在模拟盘开个 ETH 多单，保证金 3555u，3x 杠杆"
            className="chat-input"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
          />
          <button type="button" className="btn-primary" disabled={sending} onClick={send}>
            发送
          </button>
        </div>
      </div>

      <p className="cred-hint">凭证来自本机 ~/.okx/config.toml，不会把 Key 发到页面上。</p>
    </div>
  )
}

export default OkxConsole
