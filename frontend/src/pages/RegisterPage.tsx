import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert } from '../components/Alert'
import { useAuth } from '../hooks/useAuth'

export function RegisterPage() {
  const { register, login } = useAuth()
  const navigate = useNavigate()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setErrorMessage(null)
    setSuccessMessage(null)

    if (!fullName.trim()) {
      setErrorMessage('Full name is required.')
      return
    }

    if (!email.trim()) {
      setErrorMessage('Email address is required.')
      return
    }

    if (!password) {
      setErrorMessage('Password is required.')
      return
    }

    if (password !== confirmPassword) {
      setErrorMessage('Passwords do not match.')
      return
    }

    setIsLoading(true)
    try {
      await register({
        full_name: fullName.trim(),
        email: email.trim().toLowerCase(),
        password,
      })
      setSuccessMessage('Account registered successfully! Signing you in...')

      // Attempt automatic sign in
      try {
        await login({ email: email.trim().toLowerCase(), password })
        navigate('/', { replace: true })
      } catch {
        navigate('/login', { replace: true })
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Registration failed. Please verify your details.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="auth-page-container">
      <div className="auth-card">
        <div className="auth-header">
          <div className="auth-brand">
            <span className="logo-symbol">⚖</span>
            <h1>Create an Account</h1>
          </div>
          <p className="auth-subtitle">Register for double-entry financial ledger banking</p>
        </div>

        {errorMessage && (
          <Alert type="error" message={errorMessage} onClose={() => setErrorMessage(null)} />
        )}
        {successMessage && (
          <Alert type="success" message={successMessage} onClose={() => setSuccessMessage(null)} />
        )}

        <form onSubmit={handleSubmit} className="auth-form" noValidate>
          <div className="form-group">
            <label htmlFor="fullName">Full legal name</label>
            <input
              id="fullName"
              type="text"
              autoComplete="name"
              required
              className="form-control"
              placeholder="e.g. Maya Sharma"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              disabled={isLoading}
            />
          </div>

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
              autoComplete="new-password"
              required
              className="form-control"
              placeholder="••••••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="confirmPassword">Confirm password</label>
            <input
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              required
              className="form-control"
              placeholder="••••••••••••"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              disabled={isLoading}
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-block"
            disabled={isLoading}
          >
            {isLoading ? 'Creating Account...' : 'Complete Registration'}
          </button>
        </form>

        <div className="auth-footer">
          <p>
            Already have an account?{' '}
            <Link to="/login" className="text-link">
              Sign in here
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
