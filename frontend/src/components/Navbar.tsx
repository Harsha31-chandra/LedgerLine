import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { RoleBadge } from './RoleBadge'

export function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [isLoggingOut, setIsLoggingOut] = useState(false)

  const handleLogout = async () => {
    setIsLoggingOut(true)
    try {
      await logout()
      navigate('/login')
    } finally {
      setIsLoggingOut(false)
    }
  }

  return (
    <header className="navbar">
      <div className="navbar-container">
        <div className="navbar-brand-section">
          <Link to="/" className="navbar-logo">
            <span className="logo-symbol">⚖</span>
            <span className="logo-text">LedgerLine</span>
          </Link>
          <span className="badge-tag">Banking Ledger</span>
        </div>

        <nav className="navbar-nav">
          {user ? (
            <>
              <Link to="/" className="nav-link">
                Dashboard
              </Link>
              {user.role === 'ADMIN' && (
                <Link to="/admin/accounts" className="nav-link">
                  Admin Panel
                </Link>
              )}

              <div className="navbar-user">
                <span className="user-email" title={user.email}>
                  {user.full_name || user.email}
                </span>
                <RoleBadge role={user.role} type="user" />
                <button
                  type="button"
                  onClick={handleLogout}
                  disabled={isLoggingOut}
                  className="btn btn-secondary btn-sm"
                >
                  {isLoggingOut ? 'Signing out...' : 'Sign Out'}
                </button>
              </div>
            </>
          ) : (
            <div className="navbar-auth-links">
              <Link to="/login" className="nav-link">
                Sign In
              </Link>
              <Link to="/register" className="btn btn-primary btn-sm">
                Open Account
              </Link>
            </div>
          )}
        </nav>
      </div>
    </header>
  )
}
