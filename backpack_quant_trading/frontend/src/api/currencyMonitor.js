import axios from 'axios'
import request from './request'

const longRequest = (config) =>
  axios({ baseURL: '/api', timeout: 180000, withCredentials: true, ...config }).then((r) => r.data)

export const getSymbols = () => request.get('/currency-monitor/symbols')
export const getSpotSymbols = () => request.get('/currency-monitor/spot-symbols')
export const getStatus = () => request.get('/currency-monitor/status')
export const startMonitor = (data) => request.post('/currency-monitor/start', data)
export const stopMonitor = () => request.post('/currency-monitor/stop')
export const removePair = (data) => request.post('/currency-monitor/remove-pair', data)

// 合约分钟预警（波动/量能/订单簿墙）
export const getMinuteAlertStatus = () => request.get('/currency-monitor/minute-alert/status')
export const startMinuteAlert = (data) => request.post('/currency-monitor/minute-alert/start', data)
export const stopMinuteAlert = () => request.post('/currency-monitor/minute-alert/stop')

// 现货分钟预警
export const getSpotMinuteAlertStatus = () => request.get('/currency-monitor/spot-minute-alert/status')
export const startSpotMinuteAlert = (data) => request.post('/currency-monitor/spot-minute-alert/start', data)
export const stopSpotMinuteAlert = () => request.post('/currency-monitor/spot-minute-alert/stop')
export const probeSpotMinuteAlert = (params) =>
  request.get('/currency-monitor/spot-minute-alert/probe', { params })
export const testSpotMinuteDingtalk = (params) =>
  request.post('/currency-monitor/spot-minute-alert/test-dingtalk', null, { params })

// 链上活跃度监控
export const getChainActivityChains = () => request.get('/currency-monitor/chain-activity/chains')
export const getChainActivityStatus = () => request.get('/currency-monitor/chain-activity/status')
export const startChainActivity = (data) => request.post('/currency-monitor/chain-activity/start', data)
export const stopChainActivity = () => request.post('/currency-monitor/chain-activity/stop')
export const probeChainActivity = (params) =>
  request.get('/currency-monitor/chain-activity/probe', { params, timeout: 60000 })
export const checkChainActivityNow = () =>
  longRequest({
    method: 'post',
    url: '/currency-monitor/chain-activity/check-now',
    headers: (() => {
      const token = localStorage.getItem('token')
      return token ? { Authorization: `Bearer ${token}` } : {}
    })(),
  })
export const getChainRpcInfo = () => request.get('/currency-monitor/chain-activity/rpc-info')
export const testChainActivityDingtalk = () =>
  request.post('/currency-monitor/chain-activity/test-dingtalk')
