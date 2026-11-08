interface AlertProps {
  type: 'error' | 'success' | 'warning' | 'info'
  message: string
  onClose?: () => void
}

export function Alert({ type, message, onClose }: AlertProps) {
  if (!message) return null

  return (
    <div className={`alert alert-${type}`} role="alert">
      <div className="alert-content">
        <span className="alert-message">{message}</span>
      </div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="alert-close"
          aria-label="Dismiss alert"
        >
          ×
        </button>
      )}
    </div>
  )
}
