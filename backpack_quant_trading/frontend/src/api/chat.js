import request from './request'

// 聊天含 K 线分析时需拉取数据 + AI 推理，延长超时
export const sendChat = (data) => request.post('/ai-lab/chat', data, { timeout: 90000 })
