export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

function errorMessage(payload, response) {
  if (typeof payload === 'string' && payload.trim()) return payload
  if (payload?.detail) {
    return Array.isArray(payload.detail)
      ? payload.detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
      : String(payload.detail)
  }
  if (payload?.message) return String(payload.message)
  return `${response.status} ${response.statusText || '请求失败'}`
}

async function parseResponse(response, responseType) {
  if (response.status === 204) return null
  const contentType = response.headers.get('content-type') || ''
  if (!response.ok) {
    if (contentType.includes('application/json')) return response.json()
    return response.text()
  }
  if (responseType === 'blob') return response.blob()
  if (responseType === 'arrayBuffer') return response.arrayBuffer()
  if (contentType.includes('application/json')) return response.json()
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export async function request(path, options = {}) {
  const { body, responseType, headers = {}, ...init } = options
  const isForm = body instanceof FormData
  const finalHeaders = { Accept: responseType ? '*/*' : 'application/json', ...headers }
  let finalBody = body

  if (body != null && !isForm && typeof body !== 'string' && !(body instanceof Blob)) {
    finalHeaders['Content-Type'] = 'application/json'
    finalBody = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(path, { ...init, headers: finalHeaders, body: finalBody })
  } catch (error) {
    throw new ApiError(error?.message || '无法连接后端服务')
  }

  const payload = await parseResponse(response, responseType)
  if (!response.ok) throw new ApiError(errorMessage(payload, response), response.status, payload)
  return payload
}

export function unwrap(payload, keys = []) {
  if (payload == null) return payload
  for (const key of keys) {
    if (payload[key] !== undefined) return payload[key]
  }
  if (payload.data !== undefined) return unwrap(payload.data, keys)
  return payload
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
