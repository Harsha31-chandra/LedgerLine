import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { apiClient, ApiError } from '../api/client'

describe('apiClient', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    globalThis.fetch = vi.fn()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('includes credentials and accept header', async () => {
    const mockResponse = new Response(JSON.stringify({ status: 'healthy' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
    ;(globalThis.fetch as any).mockResolvedValueOnce(mockResponse)

    const result = await apiClient('/health')

    expect(result).toEqual({ status: 'healthy' })
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/health',
      expect.objectContaining({
        credentials: 'include',
        headers: expect.any(Headers),
      }),
    )
  })

  it('attaches Idempotency-Key header when provided', async () => {
    const mockResponse = new Response(JSON.stringify({ id: '123' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
    ;(globalThis.fetch as any).mockResolvedValueOnce(mockResponse)

    await apiClient('/transactions/deposit', {
      method: 'POST',
      body: { amount_paise: 5000 },
      idempotencyKey: 'test-idemp-key-1234',
    })

    const callArgs = (globalThis.fetch as any).mock.calls[0]
    const headers = callArgs[1].headers as Headers
    expect(headers.get('Idempotency-Key')).toBe('test-idemp-key-1234')
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('handles 401 Unauthorized response with custom message', async () => {
    const mockResponse = new Response(JSON.stringify({ detail: 'Session expired' }), {
      status: 401,
      statusText: 'Unauthorized',
      headers: { 'Content-Type': 'application/json' },
    })
    ;(globalThis.fetch as any).mockResolvedValueOnce(mockResponse)

    await expect(apiClient('/auth/me')).rejects.toThrow('Session expired')
  })

  it('handles 422 Unprocessable Entity with array of validation issues', async () => {
    const mockResponse = new Response(
      JSON.stringify({
        detail: [
          { loc: ['body', 'amount_paise'], msg: 'Input should be greater than 0' },
        ],
      }),
      {
        status: 422,
        statusText: 'Unprocessable Entity',
        headers: { 'Content-Type': 'application/json' },
      },
    )
    ;(globalThis.fetch as any).mockResolvedValueOnce(mockResponse)

    await expect(apiClient('/transactions/deposit', { method: 'POST' })).rejects.toThrow(
      'amount_paise: Input should be greater than 0',
    )
  })

  it('handles 409 Conflict with appropriate ApiError', async () => {
    const mockResponse = new Response(
      JSON.stringify({ detail: 'Idempotency key collision with differing payload' }),
      {
        status: 409,
        statusText: 'Conflict',
        headers: { 'Content-Type': 'application/json' },
      },
    )
    ;(globalThis.fetch as any).mockResolvedValueOnce(mockResponse)

    await expect(apiClient('/transactions/deposit', { method: 'POST' })).rejects.toThrow(
      'Idempotency key collision with differing payload',
    )
  })

  it('handles non-JSON error responses gracefully', async () => {
    const mockResponse = new Response('Rate limit exceeded from nginx gateway', {
      status: 429,
      statusText: 'Too Many Requests',
      headers: { 'Content-Type': 'text/plain' },
    })
    ;(globalThis.fetch as any).mockResolvedValueOnce(mockResponse)

    try {
      await apiClient('/test')
      expect.fail('Should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      const apiErr = err as ApiError
      expect(apiErr.status).toBe(429)
      expect(apiErr.message).toBe('Rate limit exceeded from nginx gateway')
    }
  })
})
