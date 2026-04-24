import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register } from '../api/auth'
import './Login.css'

const Login = () => {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('login')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [messageType, setMessageType] = useState('success')
  const [form, setForm] = useState({
    username: '',
    password: '',
    email: '',
    confirmPassword: '',
    remember: false,
  })

  const handleChange = (e) => {
    const { name, type, checked, value } = e.target
    setForm((prev) => ({ ...prev, [name]: type === 'checkbox' ? checked : value }))
  }

  const handleLogin = async () => {
    if (!form.username || !form.password) {
      setMessage('请输入用户名和密码')
      setMessageType('error')
      return
    }
    setLoading(true)
    setMessage('')
    try {
      const res = await login(form)
      localStorage.setItem('token', res.access_token)
      localStorage.setItem('user', JSON.stringify(res.user))
      setMessage('登录成功')
      setMessageType('success')
      navigate('/')
    } catch (e) {
      setMessage(e?.response?.data?.detail || '登录失败')
      setMessageType('error')
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async () => {
    if (!form.username || !form.password) {
      setMessage('请输入用户名和密码')
      setMessageType('error')
      return
    }
    setLoading(true)
    setMessage('')
    try {
      const res = await register(form)
      localStorage.setItem('token', res.access_token)
      localStorage.setItem('user', JSON.stringify(res.user))
      setMessage('注册成功')
      setMessageType('success')
      navigate('/')
    } catch (e) {
      setMessage(e?.response?.data?.detail || '注册失败')
      setMessageType('error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-bg"></div>
      <div className="login-card">
        <div className="login-brand">
          <div className="brand-logo-box">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" className="brand-logo-icon">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M13 10V3L4 14h7v7l9-11h-7z"
              />
            </svg>
          </div>
          <h1>ApexAI Quant</h1>
          <p>Quantitative Trading Platform</p>
        </div>

        <div className="login-tabs">
          <div className="tabs-header">
            <button
              type="button"
              className={`tab-item${activeTab === 'login' ? ' active' : ''}`}
              onClick={() => setActiveTab('login')}
            >
              登录
            </button>
          </div>

          <div className="tab-body">
            {activeTab === 'login' && (
              <>
                <div className="form-item">
                  <input
                    name="username"
                    value={form.username}
                    onChange={handleChange}
                    placeholder="用户名"
                    disabled={loading}
                  />
                </div>
                <div className="form-item">
                  <input
                    name="password"
                    type="password"
                    value={form.password}
                    onChange={handleChange}
                    placeholder="密码"
                    disabled={loading}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        handleLogin()
                      }
                    }}
                  />
                </div>
                <div className="login-extra-row">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      name="remember"
                      checked={form.remember}
                      onChange={handleChange}
                      disabled={loading}
                    />
                    记住我
                  </label>
                  <button type="button" className="link-inline" disabled>
                    忘记密码?
                  </button>
                </div>
                <div className="form-item">
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={loading}
                    onClick={handleLogin}
                  >
                    {loading ? '处理中...' : '登录'}
                  </button>
                </div>
              </>
            )}

            {activeTab === 'register' && (
              <>
                <div className="form-item">
                  <input
                    name="username"
                    value={form.username}
                    onChange={handleChange}
                    placeholder="用户名"
                    disabled={loading}
                  />
                </div>
                <div className="form-item">
                  <input
                    name="email"
                    value={form.email}
                    onChange={handleChange}
                    placeholder="邮箱（可选）"
                    disabled={loading}
                  />
                </div>
                <div className="form-item">
                  <input
                    name="password"
                    type="password"
                    value={form.password}
                    onChange={handleChange}
                    placeholder="密码"
                    disabled={loading}
                  />
                </div>
                <div className="form-item">
                  <input
                    name="confirmPassword"
                    type="password"
                    value={form.confirmPassword}
                    onChange={handleChange}
                    placeholder="确认密码"
                    disabled={loading}
                  />
                </div>
                <div className="terms-row">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      name="agree"
                      onChange={() => {}}
                    />
                    <span>
                      我同意
                      <button type="button" className="link-inline" disabled>
                        服务条款
                      </button>
                      和
                      <button type="button" className="link-inline" disabled>
                        隐私政策
                      </button>
                    </span>
                  </label>
                </div>
                <div className="form-item">
                  <button
                    type="button"
                    className="btn btn-success"
                    disabled={loading}
                    onClick={handleRegister}
                  >
                    {loading ? '处理中...' : '注册'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        {message && (
          <div className={`login-alert ${messageType === 'error' ? 'login-alert-error' : 'login-alert-success'}`}>
            {message}
          </div>
        )}

        <div className="login-footer">
          © 2024 沐龙量化. All rights reserved.
        </div>
      </div>
    </div>
  )
}

export default Login

