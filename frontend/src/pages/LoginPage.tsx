import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Alert } from '../components/Alert'
import { useAuth } from '../hooks/useAuth'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/'
  const isDemoCredentialsEnabled =
    import.meta.env.DEV || import.meta.env.VITE_ENABLE_DEMO_CREDENTIALS === 'true'

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setErrorMessage(null)

    if (!email.trim() || !password) {
      setErrorMessage('Please enter both email and password.')
      return
    }

    setIsLoading(true)
    try {
      await login({ email: email.trim(), password })
      navigate(from, { replace: true })
    } catch (err: any) {
      setErrorMessage(err.message || 'Login failed. Please check your credentials.')
    } finally {
      setIsLoading(false)
    }
  }

  const fillQuickCredentials = (demoEmail: string) => {
    setEmail(demoEmail)
    setPassword('SecurePass123!')
    setErrorMessage(null)
  }

  return (
    <div className="auth-page-container">
      <div className="auth-card">
        <div className="auth-header">
          <div className="auth-brand">
            <span className="logo-symbol">⚖</span>
            <h1>Sign in to LedgerLine</h1>
          </div>
          <p className="auth-subtitle">Secure financial transaction and ledger management</p>
        </div>

        {errorMessage && (
          <Alert type="error" message={errorMessage} onClose={() => setErrorMessage(null)} />
        )}

        <form onSubmit={handleSubmit} className="auth-form" noValidate>
          <div className="form-group">
            <label htmlFor="email">Email address</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              className="form-control"
              placeholder="user@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isLoading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              className="form-control"
              placeholder="••••••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-block"
            disabled={isLoading}
          >
            {isLoading ? 'Authenticating...' : 'Sign In'}
          </button>
        </form>

        {isDemoCredentialsEnabled && (
          <div className="quick-access-section">
            <p className="quick-access-title">Assessment Demo Credentials</p>
            <div className="quick-access-buttons">
              <button
                type="button"
                className="btn btn-outline btn-xs"
                onClick={() => fillQuickCredentials('admin@ledgerline.com')}
              >
                Admin
              </button>
              <button
                type="button"
                className="btn btn-outline btn-xs"
                onClick={() => fillQuickCredentials('holder@ledgerline.com')}
              >
                Account Holder
              </button>
              <button
                type="button"
                className="btn btn-outline btn-xs"
                onClick={() => fillQuickCredentials('auditor@ledgerline.com')}
              >
                Auditor
              </button>
            </div>
          </div>
        )}

        <div className="auth-footer">
          <p>
            Do not have an account?{' '}
            <Link to="/register" className="text-link">
              Register here
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
