import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { sendChat } from '../api/chat'
import './ChatBot.css'

const suggestQuestions = [
  '分析当前 ETH 15m K 线趋势，并给出买卖提示',
  '如何设置网格策略？',
  'ETH 当前趋势怎么看？',
  '止损止盈怎么设？',
  '网格和马丁有什么区别？',
]

const formatContent = (text) => {
  if (!text) return ''
  return text
    .replace(/\n/g, '<br/>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
}

const ChatBot = () => {
  const [panelOpen, setPanelOpen] = useState(false)
  const [inputText, setInputText] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [pos, setPos] = useState({ left: null, top: null })
  const [dragging, setDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0, left: 0, top: 0 })
  const [didDrag, setDidDrag] = useState(false)

  const messagesRef = useRef(null)
  const wrapperRef = useRef(null)

  const wrapperStyle = useMemo(() => {
    if (pos.left != null && pos.top != null) {
      return { left: `${pos.left}px`, top: `${pos.top}px`, right: 'auto', bottom: 'auto' }
    }
    return { right: '28px', bottom: '28px' }
  }, [pos.left, pos.top])

  const panelOnLeft = useMemo(() => {
    if (pos.left == null) return false
    return pos.left < window.innerWidth / 2
  }, [pos.left])

  const ensurePosition = useCallback(() => {
    if (pos.left != null) return true
    if (!wrapperRef.current) return false
    const rect = wrapperRef.current.getBoundingClientRect()
    setPos({ left: rect.left, top: rect.top })
    return true
  }, [pos.left])

  const scrollToBottom = useCallback(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [])

  useEffect(() => {
    if (panelOpen) {
      scrollToBottom()
    }
  }, [panelOpen, messages, scrollToBottom])

  const handleMouseMove = useCallback(
    (e) => {
      if (!dragging) return
      const dx = e.clientX - dragStart.x
      const dy = e.clientY - dragStart.y
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
        setDidDrag(true)
      }
      const sz = 56
      let left = dragStart.left + dx
      let top = dragStart.top + dy
      left = Math.max(0, Math.min(window.innerWidth - sz, left))
      top = Math.max(0, Math.min(window.innerHeight - sz, top))
      setPos({ left, top })
    },
    [dragStart.left, dragStart.top, dragStart.x, dragStart.y, dragging]
  )

  const handleMouseUp = useCallback(() => {
    setDragging(false)
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
  }, [handleMouseMove])

  const onAvatarMouseDown = (e) => {
    if (e.button !== 0) return
    if (!ensurePosition()) return
    setDragging(true)
    setDidDrag(false)
    setDragStart({
      x: e.clientX,
      y: e.clientY,
      left: pos.left ?? 0,
      top: pos.top ?? 0,
    })
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }

  const onAvatarClick = () => {
    if (didDrag) return
    setPanelOpen((v) => !v)
  }

  const askQuestion = (q) => {
    setInputText(q)
    void send(q)
  }

  const send = async (overrideText) => {
    const text = (overrideText ?? inputText)?.trim()
    if (!text || loading) return

    const userMsg = { role: 'user', content: text }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInputText('')
    setLoading(true)

    try {
      const history = newMessages.map((m) => ({ role: m.role, content: m.content }))
      const res = await sendChat({ message: text, history })
      setMessages((prev) => [...prev, { role: 'assistant', content: res.reply || '暂无回复' }])
    } catch (e) {
      const errMsg =
        e?.response?.data?.detail || e?.response?.data?.reply || e?.message || '请求失败，请检查网络或稍后重试。'
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: typeof errMsg === 'string' ? errMsg : '请求失败，请检查网络或稍后重试。',
        },
      ])
    } finally {
      setLoading(false)
      scrollToBottom()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  return (
    <div className="chatbot-wrapper" style={wrapperStyle} ref={wrapperRef}>
      <div
        className={`chatbot-avatar${panelOpen ? ' open' : ''}${dragging ? ' dragging' : ''}`}
        onMouseDown={onAvatarMouseDown}
        onClick={onAvatarClick}
        title="拖拽移动 · 点击提问"
      >
        <div className="avatar-inner">
          <span className="avatar-emoji">🤖</span>
        </div>
        {!panelOpen && <span className="avatar-pulse"></span>}
      </div>

      {panelOpen && (
        <div className={`chatbot-panel${panelOnLeft ? ' panel-left' : ''}`}>
          <div className="panel-header">
            <span className="panel-title">沐龙小助</span>
            <span className="panel-desc">量化交易 · 随时问答</span>
            <button
              className="panel-close"
              onClick={() => setPanelOpen(false)}
              aria-label="关闭"
              type="button"
            >
              ×
            </button>
          </div>

          <div className="panel-body">
            {messages.length === 0 ? (
              <div className="welcome-area">
                <p className="welcome-text">你好～我是沐龙量化助手，有什么可以帮你的？</p>
                <p className="guess-label">猜你想问</p>
                <div className="guess-list">
                  {suggestQuestions.map((q, i) => (
                    <button key={i} className="guess-item" type="button" onClick={() => askQuestion(q)}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="messages-area" ref={messagesRef}>
                {messages.map((m, i) => (
                  <div
                    key={i}
                    className={`msg-row ${m.role === 'user' ? 'user' : 'assistant'}`}
                  >
                    {m.role === 'assistant' && <div className="msg-avatar">🤖</div>}
                    <div className="msg-bubble">
                      <div
                        className="msg-content"
                        dangerouslySetInnerHTML={{ __html: formatContent(m.content) }}
                      />
                    </div>
                    {m.role === 'user' && <div className="msg-avatar user-avatar">我</div>}
                  </div>
                ))}
                {loading && (
                  <div className="msg-row assistant">
                    <div className="msg-avatar">🤖</div>
                    <div className="msg-bubble typing">
                      <span className="typing-dot"></span>
                      <span className="typing-dot"></span>
                      <span className="typing-dot"></span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="panel-footer">
            <textarea
              className="chat-input-textarea"
              rows={1}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入你的问题..."
            />
            <button
              className="el-button el-button--primary send-btn"
              type="button"
              disabled={loading}
              onClick={() => send()}
            >
              {loading ? '发送中...' : '发送'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default ChatBot

