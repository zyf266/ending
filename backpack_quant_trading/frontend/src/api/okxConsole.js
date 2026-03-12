import request from './request'

export const getOkxPresets = () => request.get('/okx-console/presets')

export const runOkxCommand = (payload) => request.post('/okx-console/run', payload, { timeout: 60000 })

export const runNatural = (text) => request.post('/okx-console/natural', { text }, { timeout: 60000 })

export const runAgent = (payload) => request.post('/okx-console/agent', payload, { timeout: 60000 })

