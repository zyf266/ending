import request from './request'

export const getCryptoSignalConfig = () => request.get('/crypto-signal-hub/config')
export const saveCryptoSignalConfig = (data) => request.put('/crypto-signal-hub/config', data)
export const getUptrendScan = () => request.get('/crypto-signal-hub/scan')
export const runUptrendScan = () => request.post('/crypto-signal-hub/scan/run')
export const runUptrendScanSync = () => request.post('/crypto-signal-hub/scan/run-sync')
export const getScoreHistory = (limit = 30) =>
  request.get('/crypto-signal-hub/score/history', { params: { limit } })
export const testSignalScore = (data) => request.post('/crypto-signal-hub/score/test', data)
export const testCryptoDingtalk = (text) =>
  request.post('/crypto-signal-hub/test-dingtalk', text ? { text } : {})
