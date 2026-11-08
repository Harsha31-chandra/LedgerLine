import type { ApiErrorResponse } from '../types/api'

export class ApiError extends Error {
  public status: number
  public statusText: string
  public data: ApiErrorResponse | null

  constructor(status: number, statusText: string, data: ApiErrorResponse | null, message?: string) {
    super(message || ApiError.formatMessage(status, data, statusText))
    this.name = 'ApiError'
    this.status = status
    this.statusText = statusText
    this.data = data
  }

  private static formatMessage(status: number, data: ApiErrorResponse | null, statusText: string): string {
    if (data?.detail) {
      if (typeof data.detail === 'string') {
        return data.detail
      }
      if (Array.isArray(data.detail)) {
        return data.detail
          .map((item) => {
            const loc = item.loc ? item.loc.filter((part) => part !== 'body').join('.') : ''
            return loc ? `${loc}: ${item.msg}` : (item.msg || 'Validation error')
          })
          .join(', ')
      }
    }
    if (data?.message) {
      return data.message
    }
    if (status === 401) {
      return 'Authentication required. Please log in.'
    }
    if (status === 403) {
      return 'Access denied. You do not have permission for this action.'
    }
    if (status === 404) {
      return 'Requested resource not found.'
    }
    if (status === 409) {
      return 'Resource conflict or duplicate operation.'
    }
    if (status === 422) {
      return 'Validation error. Please check your inputs.'
    }
    if (status === 429) {
      return 'Rate limit exceeded. Please wait a moment and try again.'
    }
    return statusText || `Request failed with status ${status}`
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  idempotencyKey?: string
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

export async function apiClient<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers: customHeaders, idempotencyKey, ...fetchOptions } = options

  const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`

  const headers = new Headers(customHeaders || {})
  headers.set('Accept', 'application/json')

  let formattedBody: BodyInit | undefined = undefined

  if (body !== undefined) {
    headers.set('Content-Type', 'application/json')
    formattedBody = JSON.stringify(body)
  }

  if (idempotencyKey) {
    headers.set('Idempotency-Key', idempotencyKey)
  }

  const response = await fetch(url, {
    ...fetchOptions,
    headers,
    credentials: 'include',
    body: formattedBody,
  })

  // Parse response
  const contentType = response.headers.get('content-type') || ''
  const isJson = contentType.includes('application/json')

  let data: any = null
  if (isJson) {
    try {
      data = await response.json()
    } catch {
      data = null
    }
  } else {
    try {
      const text = await response.text()
      if (text) {
        data = { message: text }
      }
    } catch {
      data = null
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, response.statusText, data)
  }

  return data as T
}
