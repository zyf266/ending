import request from './request'

export function getOkxAgentCapabilities() {
  return request.get('/okx-agent/capabilities')
}

export function getOkxAgentQuickstart() {
  return request.get('/okx-agent/quickstart')
}

export function getOkxAgentFaq() {
  return request.get('/okx-agent/faq')
}
