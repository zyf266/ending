import request from './request'

export const getGridSymbols = () => request.get('/grid/symbols')
export const getGridStatus = () => request.get('/grid/status')
export const startGrid = (data) => request.post('/grid/start', data)
export const stopGrid = (id) => request.post(`/grid/stop/${id}`)
export const stopAllGrids = () => request.post('/grid/stop-all')
