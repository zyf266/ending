import request from './request'

export const getStrategies = () => request.get('/trading/strategies')
export const getInstances = () => request.get('/trading/instances')
export const launchStrategy = (data) => request.post('/trading/launch', data)
export const stopInstance = (id) => request.delete(`/trading/instances/${id}`)
export const getLogs = () => request.get('/trading/logs')
