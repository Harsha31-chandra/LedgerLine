import { useEffect } from 'react'

interface ToastProps {
  message: string | null
  type?: 'success' | 'error' | 'info'
  onClose: () => void
  durationMs?: number
}

export function Toast({ message, type = 'success', onClose, durationMs = 4000 }: ToastProps) {
  useEffect(() => {
    if (!message) return
    const timer = setTimeout(() => {
      onClose()
    }, durationMs)
    return () => clearTimeout(timer)
  }, [message, onClose, durationMs])

  if (!message) return null

  return (
    <div className={`toast-notification toast-${type}`} role="alert" aria-live="assertive">
      <div className="toast-content">
        <span className="toast-icon">
          {type === 'success' && '✓'}
          {type === 'error' && '✕'}
          {type === 'info' && 'ℹ'}
        </span>
        <span className="toast-message">{message}</span>
      </div>
      <button
        type="button"
        className="toast-close"
        onClick={onClose}
        aria-label="Dismiss notification"
      >
        ×
      </button>
    </div>
  )
}
