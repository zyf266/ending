import request from './request'

export const getDashboard = (exchange = 'backpack') =>
  request.get('/dashboard/summary', { params: { exchange } })
