import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listAccounts } from '../api/accounts'
import { Alert } from '../components/Alert'
import { CurrencyAmount } from '../components/CurrencyAmount'
import { RoleBadge } from '../components/RoleBadge'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../hooks/useAuth'
import type { AccountWithMembership } from '../types/api'

export function DashboardPage() {
  const { user } = useAuth()
  const [accounts, setAccounts] = useState<AccountWithMembership[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const fetchAccounts = useCallback(async () => {
    setIsLoading(true)
    setErrorMessage(null)
    try {
      const data = await listAccounts()
      setAccounts(data)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load financial accounts.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let isMounted = true
    listAccounts()
      .then((data) => {
        if (isMounted) {
          setAccounts(data)
        }
      })
      .catch((err: any) => {
        if (isMounted) {
          setErrorMessage(err.message || 'Failed to load financial accounts.')
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

  // Calculate aggregated balance for active accounts owned/accessible
  const totalBalancePaise = accounts.reduce((acc, account) => acc + account.balance, 0)

  return (
    <div className="page-container">
      <div className="dashboard-header">
        <div>
          <div className="user-greeting">
            <h1>Welcome, {user?.full_name}</h1>
            <RoleBadge role={user?.role || 'HOLDER'} type="user" />
          </div>
          <p className="text-muted">
            Authenticated as <span className="font-medium text-dark">{user?.email}</span>
          </p>
        </div>

        {user?.role === 'ADMIN' && (
          <div className="dashboard-actions">
            <Link to="/admin/accounts" className="btn btn-primary">
              + Admin Controls
            </Link>
          </div>
        )}
      </div>

      {errorMessage && (
        <Alert
          type="error"
          message={errorMessage}
          onClose={() => setErrorMessage(null)}
        />
      )}

      {/* Aggregate Overview Card */}
      {!isLoading && accounts.length > 0 && (
        <div className="stats-grid">
          <div className="stat-card">
            <span className="stat-label">Accessible Accounts</span>
            <span className="stat-value">{accounts.length}</span>
          </div>
          <div className="stat-card">
            <span className="stat-label">Total Portfolio Balance</span>
            <span className="stat-value text-primary">
              <CurrencyAmount amountPaise={totalBalancePaise} />
            </span>
          </div>
        </div>
      )}

      {/* Accounts List Section */}
      <div className="section-container">
        <div className="section-header">
          <h2>Your Financial Accounts</h2>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={fetchAccounts}
            disabled={isLoading}
          >
            {isLoading ? 'Refreshing...' : '↻ Refresh'}
          </button>
        </div>

        {isLoading ? (
          <div className="loading-state">
            <div className="spinner" />
            <p>Loading accounts from ledger...</p>
          </div>
        ) : accounts.length === 0 ? (
          <div className="empty-state-card">
            <div className="empty-icon">📁</div>
            <h3>No Accounts Found</h3>
            <p className="text-muted">
              {user?.role === 'ADMIN'
                ? 'No financial accounts have been created yet. You can create accounts in the Admin Panel.'
                : 'You do not currently have membership in any accounts. Contact an administrator to be assigned to an account.'}
            </p>
            {user?.role === 'ADMIN' && (
              <Link to="/admin/accounts" className="btn btn-primary">
                Open Admin Account Console
              </Link>
            )}
          </div>
        ) : (
          <div className="accounts-grid">
            {accounts.map((account) => (
              <div key={account.id} className="account-card">
                <div className="account-card-header">
                  <div>
                    <h3 className="account-card-title">{account.account_name}</h3>
                    <span className="account-number">{account.account_number}</span>
                  </div>
                  <div className="badge-group">
                    <StatusBadge status={account.status} />
                    <RoleBadge role={account.membership_role} type="membership" />
                  </div>
                </div>

                <div className="account-card-balance">
                  <span className="balance-label">Current Balance</span>
                  <div className="balance-value">
                    <CurrencyAmount
                      amountPaise={account.balance}
                      currency={account.currency}
                    />
                  </div>
                </div>

                <div className="account-card-footer">
                  <span className="currency-badge">{account.currency}</span>
                  <Link
                    to={`/accounts/${account.id}`}
                    className="btn btn-primary btn-sm"
                  >
                    View Account & Statement →
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
