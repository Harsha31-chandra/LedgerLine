import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { createAccount, getAdminAccounts, updateAccountStatus } from '../api/accounts'
import {
  assignAccountMembership,
  getAdminAuditLogs,
  getAdminStats,
  getAdminUsers,
} from '../api/admin'
import { Alert } from '../components/Alert'
import { CurrencyAmount } from '../components/CurrencyAmount'
import { Modal } from '../components/Modal'
import { RoleBadge } from '../components/RoleBadge'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../hooks/useAuth'
import type {
  Account,
  AccountStatus,
  AdminStats,
  AdminUser,
  AuditEvent,
  MembershipRole,
} from '../types/api'

type AdminTab = 'accounts' | 'users' | 'audit'

export function AdminAccountsPage() {
  const { user, isLoading: isAuthLoading } = useAuth()
  const [activeTab, setActiveTab] = useState<AdminTab>('accounts')

  // Accounts state
  const [accounts, setAccounts] = useState<Account[]>([])
  const [isLoading, setIsLoading] = useState(user?.role === 'ADMIN')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  // Stats state
  const [stats, setStats] = useState<AdminStats | null>(null)

  // Users state
  const [usersList, setUsersList] = useState<AdminUser[]>([])
  const [isLoadingUsers, setIsLoadingUsers] = useState(false)

  // Audit state
  const [auditLogs, setAuditLogs] = useState<AuditEvent[]>([])
  const [isLoadingAudit, setIsLoadingAudit] = useState(false)
  const [auditActionFilter, setAuditActionFilter] = useState<string>('')

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [selectedAccountForStatus, setSelectedAccountForStatus] = useState<Account | null>(null)
  const [isAssignModalOpen, setIsAssignModalOpen] = useState(false)

  // Create Form State
  const [accountName, setAccountName] = useState('')
  const [currency, setCurrency] = useState('INR')
  const [ownerUserId, setOwnerUserId] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // Status Form State
  const [statusVal, setStatusVal] = useState<AccountStatus>('ACTIVE')

  // Membership Form State
  const [assignAccountId, setAssignAccountId] = useState('')
  const [assignUserId, setAssignUserId] = useState('')
  const [assignRole, setAssignRole] = useState<MembershipRole>('OPERATOR')

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

  const fetchStats = useCallback(async () => {
    try {
      const s = await getAdminStats()
      setStats(s)
    } catch {
      // Non-fatal if stats query fails
    }
  }, [])

  const fetchUsers = useCallback(async () => {
    setIsLoadingUsers(true)
    try {
      const u = await getAdminUsers()
      setUsersList(u)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load user directory.')
    } finally {
      setIsLoadingUsers(false)
    }
  }, [])

  const fetchAuditLogs = useCallback(async (action?: string) => {
    setIsLoadingAudit(true)
    try {
      const logs = await getAdminAuditLogs(50, 0, action || undefined)
      setAuditLogs(logs)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load audit logs.')
    } finally {
      setIsLoadingAudit(false)
    }
  }, [])

  useEffect(() => {
    if (user?.role !== 'ADMIN') return

    let isMounted = true
    getAdminAccounts()
      .then((data) => {
        if (isMounted) setAccounts(data)
      })
      .catch((err: any) => {
        if (isMounted) setErrorMessage(err.message || 'Failed to retrieve accounts.')
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })

    getAdminStats().then((s) => {
      if (isMounted) setStats(s)
    }).catch(() => {})

    return () => {
      isMounted = false
    }
  }, [user?.role])

  useEffect(() => {
    if (user?.role !== 'ADMIN') return
    Promise.resolve().then(() => {
      if (activeTab === 'users' && usersList.length === 0) {
        fetchUsers()
      } else if (activeTab === 'audit' && auditLogs.length === 0) {
        fetchAuditLogs(auditActionFilter)
      }
    })
  }, [activeTab, user?.role, fetchUsers, fetchAuditLogs, usersList.length, auditLogs.length, auditActionFilter])

  if (isAuthLoading) {
    return (
      <div className="page-container">
        <div className="loading-state">
          <div className="spinner" />
          <p>Verifying administrator credentials...</p>
        </div>
      </div>
    )
  }

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
      await Promise.all([fetchAccounts(), fetchStats()])
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
      await Promise.all([fetchAccounts(), fetchStats()])
    } catch (err: any) {
      setFormError(err.message || 'Failed to update account status.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleAssignSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!assignAccountId || !assignUserId) {
      setFormError('Both Account ID and User ID are required.')
      return
    }

    setIsSubmitting(true)
    setFormError(null)
    try {
      const res = await assignAccountMembership({
        account_id: assignAccountId.trim(),
        user_id: assignUserId.trim(),
        role: assignRole,
      })
      setSuccessMessage(res.message || 'Membership assigned successfully.')
      setIsAssignModalOpen(false)
      setAssignAccountId('')
      setAssignUserId('')
      if (activeTab === 'users') await fetchUsers()
    } catch (err: any) {
      setFormError(err.message || 'Failed to assign account membership.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="page-container">
      {/* Breadcrumb & Header */}
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

        <div className="dashboard-actions-header">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setFormError(null)
              if (accounts.length > 0 && !assignAccountId) setAssignAccountId(accounts[0].id)
              setIsAssignModalOpen(true)
            }}
          >
            Assign Membership
          </button>
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

      {/* Global Summary Stat Cards */}
      {stats && (
        <div className="metrics-grid mb-6">
          <div className="metric-card">
            <div className="metric-header">
              <span className="metric-title">Total Users</span>
              <span className="metric-badge">System</span>
            </div>
            <div className="metric-value font-mono">{stats.total_users}</div>
            <div className="metric-footer">Registered system principals</div>
          </div>

          <div className="metric-card">
            <div className="metric-header">
              <span className="metric-title">Total Accounts</span>
              <span className="metric-badge font-mono">{stats.active_accounts} Active</span>
            </div>
            <div className="metric-value font-mono">{stats.total_accounts}</div>
            <div className="metric-footer text-muted">
              {stats.frozen_accounts} Frozen • {stats.closed_accounts} Closed
            </div>
          </div>

          <div className="metric-card">
            <div className="metric-header">
              <span className="metric-title">Portfolio Balance</span>
              <span className="metric-badge">Active</span>
            </div>
            <div className="metric-value font-mono text-emerald">
              <CurrencyAmount amountPaise={stats.total_portfolio_balance_paise} currency="INR" />
            </div>
            <div className="metric-footer">Combined liquid balances</div>
          </div>

          <div className="metric-card">
            <div className="metric-header">
              <span className="metric-title">Total Transactions</span>
              <span className="metric-badge">Ledger</span>
            </div>
            <div className="metric-value font-mono">{stats.total_transactions}</div>
            <div className="metric-footer">Immutable posted movements</div>
          </div>
        </div>
      )}

      {/* Alerts */}
      {errorMessage && (
        <Alert type="error" message={errorMessage} onClose={() => setErrorMessage(null)} />
      )}
      {successMessage && (
        <Alert type="success" message={successMessage} onClose={() => setSuccessMessage(null)} />
      )}

      {/* Administrative Tabs */}
      <div className="admin-tabs-nav mb-4">
        <button
          type="button"
          className={`admin-tab-btn ${activeTab === 'accounts' ? 'active' : ''}`}
          onClick={() => setActiveTab('accounts')}
        >
          Accounts Registry ({accounts.length})
        </button>
        <button
          type="button"
          className={`admin-tab-btn ${activeTab === 'users' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('users')
            fetchUsers()
          }}
        >
          User Directory
        </button>
        <button
          type="button"
          className={`admin-tab-btn ${activeTab === 'audit' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('audit')
            fetchAuditLogs(auditActionFilter)
          }}
        >
          Audit Trail Monitoring
        </button>
      </div>

      {/* TAB 1: ACCOUNTS REGISTRY */}
      {activeTab === 'accounts' && (
        <div className="section-container">
          <div className="section-header">
            <h2>Accounts in System</h2>
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={() => {
                fetchAccounts()
                fetchStats()
              }}
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
                        <div className="flex justify-end gap-2">
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
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: USER DIRECTORY */}
      {activeTab === 'users' && (
        <div className="section-container">
          <div className="section-header">
            <h2>System Users</h2>
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={fetchUsers}
              disabled={isLoadingUsers}
            >
              {isLoadingUsers ? 'Refreshing...' : '↻ Refresh'}
            </button>
          </div>

          {isLoadingUsers ? (
            <div className="loading-state">
              <div className="spinner" />
              <p>Loading user directory...</p>
            </div>
          ) : usersList.length === 0 ? (
            <div className="empty-state-card">
              <h3>No Users Found</h3>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="statement-table">
                <thead>
                  <tr>
                    <th>Full Name</th>
                    <th>Email Address</th>
                    <th>System Role</th>
                    <th>Status</th>
                    <th>Linked Accounts</th>
                    <th>User ID (UUID)</th>
                    <th className="text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {usersList.map((u) => (
                    <tr key={u.id}>
                      <td className="font-medium text-dark">{u.full_name}</td>
                      <td>{u.email}</td>
                      <td>
                        <RoleBadge role={u.role} type="user" />
                      </td>
                      <td>
                        <span className={`status-pill ${u.is_active ? 'active' : 'closed'}`}>
                          {u.is_active ? 'Active' : 'Disabled'}
                        </span>
                      </td>
                      <td className="font-mono">{u.account_count} accounts</td>
                      <td className="font-mono text-xs text-muted" title={u.id}>
                        {u.id}
                      </td>
                      <td className="text-right">
                        <button
                          type="button"
                          className="btn btn-secondary btn-xs"
                          onClick={() => {
                            setAssignUserId(u.id)
                            if (accounts.length > 0) setAssignAccountId(accounts[0].id)
                            setFormError(null)
                            setIsAssignModalOpen(true)
                          }}
                        >
                          Assign Membership
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: AUDIT TRAIL MONITORING */}
      {activeTab === 'audit' && (
        <div className="section-container">
          <div className="section-header flex justify-between items-center">
            <div>
              <h2>Audit Event Log</h2>
              <p className="text-muted text-xs">Tamper-evident record of all system and financial actions</p>
            </div>
            <div className="flex gap-2 items-center">
              <select
                className="form-control form-control-sm"
                value={auditActionFilter}
                onChange={(e) => {
                  setAuditActionFilter(e.target.value)
                  fetchAuditLogs(e.target.value)
                }}
              >
                <option value="">All Actions</option>
                <option value="ACCOUNT_CREATED">ACCOUNT_CREATED</option>
                <option value="ACCOUNT_STATUS_CHANGED">ACCOUNT_STATUS_CHANGED</option>
                <option value="MEMBERSHIP_ASSIGNED">MEMBERSHIP_ASSIGNED</option>
                <option value="TRANSACTION_DEPOSIT">TRANSACTION_DEPOSIT</option>
                <option value="TRANSACTION_WITHDRAWAL">TRANSACTION_WITHDRAWAL</option>
                <option value="TRANSACTION_TRANSFER">TRANSACTION_TRANSFER</option>
              </select>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => fetchAuditLogs(auditActionFilter)}
                disabled={isLoadingAudit}
              >
                {isLoadingAudit ? 'Refreshing...' : '↻ Refresh'}
              </button>
            </div>
          </div>

          {isLoadingAudit ? (
            <div className="loading-state">
              <div className="spinner" />
              <p>Loading audit trail...</p>
            </div>
          ) : auditLogs.length === 0 ? (
            <div className="empty-state-card">
              <h3>No Audit Events Found</h3>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="statement-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Action</th>
                    <th>Entity Type</th>
                    <th>Entity ID</th>
                    <th>Actor</th>
                    <th>IP Address</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((log) => (
                    <tr key={log.id}>
                      <td className="font-mono text-xs text-muted">
                        {new Date(log.created_at).toLocaleString()}
                      </td>
                      <td>
                        <span className="badge-tag">{log.action}</span>
                      </td>
                      <td>{log.entity_type}</td>
                      <td className="font-mono text-xs text-muted" title={log.entity_id || ''}>
                        {log.entity_id ? log.entity_id.slice(0, 8) + '...' : '—'}
                      </td>
                      <td className="text-xs">
                        {log.actor_name ? `${log.actor_name} (${log.actor_email})` : log.actor_user_id || 'System'}
                      </td>
                      <td className="font-mono text-xs text-muted">{log.ip_address || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

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

      {/* Modal: Assign Membership */}
      <Modal
        isOpen={isAssignModalOpen}
        onClose={() => !isSubmitting && setIsAssignModalOpen(false)}
        title="Assign Account Membership"
      >
        <form onSubmit={handleAssignSubmit}>
          {formError && <Alert type="error" message={formError} onClose={() => setFormError(null)} />}

          <div className="form-group">
            <label htmlFor="assign-acc">Account</label>
            {accounts.length > 0 ? (
              <select
                id="assign-acc"
                className="form-control"
                value={assignAccountId}
                onChange={(e) => setAssignAccountId(e.target.value)}
                disabled={isSubmitting}
                required
              >
                {accounts.map((acc) => (
                  <option key={acc.id} value={acc.id}>
                    {acc.account_name} ({acc.account_number})
                  </option>
                ))}
              </select>
            ) : (
              <input
                id="assign-acc"
                type="text"
                className="form-control font-mono"
                placeholder="Account UUID"
                value={assignAccountId}
                onChange={(e) => setAssignAccountId(e.target.value)}
                disabled={isSubmitting}
                required
              />
            )}
          </div>

          <div className="form-group">
            <label htmlFor="assign-user">User ID (UUID)</label>
            <input
              id="assign-user"
              type="text"
              className="form-control font-mono"
              placeholder="e.g. 1a2b3c4d-..."
              value={assignUserId}
              onChange={(e) => setAssignUserId(e.target.value)}
              disabled={isSubmitting}
              required
            />
            <span className="field-hint">Copy UUID from User Directory tab</span>
          </div>

          <div className="form-group">
            <label htmlFor="assign-role">Membership Role</label>
            <select
              id="assign-role"
              className="form-control"
              value={assignRole}
              onChange={(e) => setAssignRole(e.target.value as MembershipRole)}
              disabled={isSubmitting}
            >
              <option value="VIEWER">VIEWER (Read-only)</option>
              <option value="OPERATOR">OPERATOR (Deposit, Withdraw, Transfer)</option>
              <option value="OWNER">OWNER (Full Account Management)</option>
            </select>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsAssignModalOpen(false)}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Assigning...' : 'Assign Membership'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
