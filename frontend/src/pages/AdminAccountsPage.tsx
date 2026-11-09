import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { createAccount, getAdminAccounts, updateAccountStatus } from '../api/accounts'
import { Alert } from '../components/Alert'
import { CurrencyAmount } from '../components/CurrencyAmount'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../hooks/useAuth'
import type { Account, AccountStatus } from '../types/api'

export function AdminAccountsPage() {
  const { user } = useAuth()
  const [accounts, setAccounts] = useState<Account[]>([])
  const [isLoading, setIsLoading] = useState(user?.role === 'ADMIN')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [selectedAccountForStatus, setSelectedAccountForStatus] = useState<Account | null>(null)

  // Create Form State
  const [accountName, setAccountName] = useState('')
  const [currency, setCurrency] = useState('INR')
  const [ownerUserId, setOwnerUserId] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // Status Form State
  const [statusVal, setStatusVal] = useState<AccountStatus>('ACTIVE')

  const fetchAccounts = useCallback(async () => {
    setIsLoading(true)
    setErrorMessage(null)
    try {
      const data = await getAdminAccounts()
      setAccounts(data)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to retrieve accounts.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (user?.role !== 'ADMIN') {
      return
    }
    let isMounted = true
    getAdminAccounts()
      .then((data) => {
        if (isMounted) {
          setAccounts(data)
        }
      })
      .catch((err: any) => {
        if (isMounted) {
          setErrorMessage(err.message || 'Failed to retrieve accounts.')
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
  }, [user?.role])

  if (user?.role !== 'ADMIN') {
    return (
      <div className="page-container">
        <Alert
          type="error"
          message="Unauthorized access. Administrator privileges are required to view this console."
        />
        <div className="mt-4">
          <Link to="/" className="btn btn-secondary">
            ← Return to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  const handleCreateSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!accountName.trim()) {
      setFormError('Account name is required.')
      return
    }

    setIsSubmitting(true)
    setFormError(null)
    try {
      const created = await createAccount({
        account_name: accountName.trim(),
        currency: currency.trim().toUpperCase() || 'INR',
        owner_user_id: ownerUserId.trim() || undefined,
      })
      setSuccessMessage(`Account "${created.account_name}" (${created.account_number}) created successfully.`)
      setIsCreateModalOpen(false)
      setAccountName('')
      setOwnerUserId('')
      await fetchAccounts()
    } catch (err: any) {
      setFormError(err.message || 'Failed to create financial account.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleStatusSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!selectedAccountForStatus) return

    setIsSubmitting(true)
    setFormError(null)
    try {
      await updateAccountStatus(selectedAccountForStatus.id, { status: statusVal })
      setSuccessMessage(`Account status updated to ${statusVal}.`)
      setSelectedAccountForStatus(null)
      await fetchAccounts()
    } catch (err: any) {
      setFormError(err.message || 'Failed to update account status.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="page-container">
      <div className="dashboard-header">
        <div>
          <div className="breadcrumb mb-2">
            <Link to="/" className="text-link">Dashboard</Link>
            <span className="breadcrumb-separator">/</span>
            <span className="breadcrumb-current">Admin Console</span>
          </div>
          <h1>Administrative Account Console</h1>
          <p className="text-muted">
            Manage system accounts, create new customer ledger entities, and govern lifecycle states.
          </p>
        </div>

        <div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setFormError(null)
              setIsCreateModalOpen(true)
            }}
          >
            + Create New Account
          </button>
        </div>
      </div>

      {errorMessage && (
        <Alert type="error" message={errorMessage} onClose={() => setErrorMessage(null)} />
      )}
      {successMessage && (
        <Alert type="success" message={successMessage} onClose={() => setSuccessMessage(null)} />
      )}

      <div className="section-container mt-6">
        <div className="section-header">
          <h2>Accounts in System</h2>
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
            <p>Loading administrative account registry...</p>
          </div>
        ) : accounts.length === 0 ? (
          <div className="empty-state-card">
            <h3>No Accounts Found</h3>
            <p className="text-muted">Use the button above to create the first account.</p>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="statement-table">
              <thead>
                <tr>
                  <th>Account Number</th>
                  <th>Account Name</th>
                  <th>Currency</th>
                  <th className="text-right">Balance</th>
                  <th>Status</th>
                  <th>Account ID (UUID)</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((acc) => (
                  <tr key={acc.id}>
                    <td className="font-mono font-medium">{acc.account_number}</td>
                    <td className="font-medium text-dark">{acc.account_name}</td>
                    <td>{acc.currency}</td>
                    <td className="text-right">
                      <CurrencyAmount amountPaise={acc.balance} currency={acc.currency} />
                    </td>
                    <td>
                      <StatusBadge status={acc.status} />
                    </td>
                    <td className="font-mono text-xs text-muted" title={acc.id}>
                      {acc.id}
                    </td>
                    <td className="text-right">
                      <button
                        type="button"
                        className="btn btn-secondary btn-xs"
                        onClick={() => {
                          setSelectedAccountForStatus(acc)
                          setStatusVal(acc.status)
                          setFormError(null)
                        }}
                      >
                        Status
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal: Create Account */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => !isSubmitting && setIsCreateModalOpen(false)}
        title="Create Financial Account"
      >
        <form onSubmit={handleCreateSubmit}>
          {formError && <Alert type="error" message={formError} onClose={() => setFormError(null)} />}

          <div className="form-group">
            <label htmlFor="create-name">Account Name</label>
            <input
              id="create-name"
              type="text"
              required
              maxLength={100}
              className="form-control"
              placeholder="e.g. Acme Corp Treasury"
              value={accountName}
              onChange={(e) => setAccountName(e.target.value)}
              disabled={isSubmitting}
              autoFocus
            />
          </div>

          <div className="form-group">
            <label htmlFor="create-currency">Currency</label>
            <input
              id="create-currency"
              type="text"
              required
              maxLength={3}
              className="form-control uppercase"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              disabled={isSubmitting}
            />
            <span className="field-hint">Standard 3-letter ISO currency (default INR)</span>
          </div>

          <div className="form-group">
            <label htmlFor="create-owner">Owner User ID (optional UUID)</label>
            <input
              id="create-owner"
              type="text"
              className="form-control font-mono"
              placeholder="Leave empty to assign yourself (Admin) as OWNER"
              value={ownerUserId}
              onChange={(e) => setOwnerUserId(e.target.value)}
              disabled={isSubmitting}
            />
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsCreateModalOpen(false)}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Creating...' : 'Create Account'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Change Status */}
      <Modal
        isOpen={selectedAccountForStatus !== null}
        onClose={() => !isSubmitting && setSelectedAccountForStatus(null)}
        title={`Change Status: ${selectedAccountForStatus?.account_name}`}
      >
        <form onSubmit={handleStatusSubmit}>
          {formError && <Alert type="error" message={formError} onClose={() => setFormError(null)} />}

          <div className="form-group">
            <label htmlFor="admin-change-status">Lifecycle Status</label>
            <select
              id="admin-change-status"
              className="form-control"
              value={statusVal}
              onChange={(e) => setStatusVal(e.target.value as AccountStatus)}
              disabled={isSubmitting}
            >
              <option value="ACTIVE">ACTIVE</option>
              <option value="FROZEN">FROZEN</option>
              <option value="CLOSED">CLOSED</option>
            </select>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setSelectedAccountForStatus(null)}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Updating...' : 'Save Status'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
