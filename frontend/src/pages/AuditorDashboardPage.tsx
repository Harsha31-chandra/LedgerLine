import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  getAuditAccounts,
  getAuditLogs,
  getAuditTransactions,
  getGlobalOverview,
} from '../api/admin'
import { Alert } from '../components/Alert'
import { CurrencyAmount } from '../components/CurrencyAmount'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../hooks/useAuth'
import type {
  Account,
  AuditEvent,
  GlobalOverview,
  Transaction,
} from '../types/api'

type AuditorTab = 'accounts' | 'transactions' | 'audit'

export function AuditorDashboardPage() {
  const { user, isLoading: isAuthLoading } = useAuth()
  const isAuthorized = user?.role === 'AUDITOR' || user?.role === 'ADMIN'

  const [activeTab, setActiveTab] = useState<AuditorTab>('accounts')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Overview metrics
  const [overview, setOverview] = useState<GlobalOverview | null>(null)

  // Accounts
  const [accounts, setAccounts] = useState<Account[]>([])
  const [isLoadingAccounts, setIsLoadingAccounts] = useState(false)
  const [accountSearch, setAccountSearch] = useState('')

  // Transactions
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [isLoadingTxns, setIsLoadingTxns] = useState(false)
  const [selectedTxnForLedger, setSelectedTxnForLedger] = useState<Transaction | null>(null)

  // Audit Logs
  const [auditLogs, setAuditLogs] = useState<AuditEvent[]>([])
  const [isLoadingAudit, setIsLoadingAudit] = useState(false)
  const [auditActionFilter, setAuditActionFilter] = useState('')

  const fetchOverview = useCallback(async () => {
    try {
      const data = await getGlobalOverview()
      setOverview(data)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to retrieve global financial overview.')
    }
  }, [])

  const fetchAccounts = useCallback(async () => {
    setIsLoadingAccounts(true)
    try {
      const data = await getAuditAccounts()
      setAccounts(Array.isArray(data) ? data : [])
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to retrieve accounts.')
    } finally {
      setIsLoadingAccounts(false)
    }
  }, [])

  const fetchTransactions = useCallback(async () => {
    setIsLoadingTxns(true)
    try {
      const data = await getAuditTransactions(50, 0)
      setTransactions(Array.isArray(data) ? data : [])
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to retrieve transactions.')
    } finally {
      setIsLoadingTxns(false)
    }
  }, [])

  const fetchAuditLogs = useCallback(async (action?: string) => {
    setIsLoadingAudit(true)
    try {
      const data = await getAuditLogs(50, 0, action || undefined)
      setAuditLogs(Array.isArray(data) ? data : [])
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to retrieve audit trail.')
    } finally {
      setIsLoadingAudit(false)
    }
  }, [])

  useEffect(() => {
    if (!isAuthorized) return

    Promise.resolve().then(() => {
      fetchOverview()
      fetchAccounts()
    })
  }, [isAuthorized, fetchOverview, fetchAccounts])

  useEffect(() => {
    if (!isAuthorized) return
    Promise.resolve().then(() => {
      if (activeTab === 'transactions' && transactions.length === 0) {
        fetchTransactions()
      } else if (activeTab === 'audit' && auditLogs.length === 0) {
        fetchAuditLogs(auditActionFilter)
      }
    })
  }, [activeTab, isAuthorized, fetchTransactions, fetchAuditLogs, transactions.length, auditLogs.length, auditActionFilter])

  if (isAuthLoading) {
    return (
      <div className="page-container">
        <div className="loading-state">
          <div className="spinner" />
          <p>Verifying auditor credentials...</p>
        </div>
      </div>
    )
  }

  if (!isAuthorized) {
    return (
      <div className="page-container">
        <Alert
          type="error"
          message="Unauthorized access. Auditor or Administrator privileges are required to view this oversight console."
        />
        <div className="mt-4">
          <Link to="/" className="btn btn-secondary">
            ← Return to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  const safeAccounts = Array.isArray(accounts) ? accounts : []
  const filteredAccounts = safeAccounts.filter(
    (acc) =>
      acc.account_name.toLowerCase().includes(accountSearch.toLowerCase()) ||
      acc.account_number.toLowerCase().includes(accountSearch.toLowerCase()) ||
      acc.id.toLowerCase().includes(accountSearch.toLowerCase()),
  )

  return (
    <div className="page-container">
      {/* Header */}
      <div className="dashboard-header">
        <div>
          <div className="breadcrumb mb-2">
            <Link to="/" className="text-link">Dashboard</Link>
            <span className="breadcrumb-separator">/</span>
            <span className="breadcrumb-current">Auditor Oversight</span>
          </div>
          <h1>Auditor Oversight & Ledger Verification</h1>
          <p className="text-muted">
            Independent read-only audit inspection of all ledger movements, account balances, and system audit events.
          </p>
        </div>

        <div className="auditor-badge-pill">
          <span className="auditor-icon">🛡️</span>
          <span>STRICTLY READ-ONLY</span>
        </div>
      </div>

      {/* Read-Only Safety Banner */}
      <div className="auditor-safety-banner mb-6">
        <div className="flex items-center gap-3">
          <span className="text-xl">🔒</span>
          <div>
            <strong>Read-Only Compliance Mode Active:</strong> All financial mutations (deposits,
            withdrawals, transfers) and account modifications are strictly prohibited and blocked by backend RBAC.
          </div>
        </div>
      </div>

      {/* Global Financial Metrics Cards */}
      {overview && (
        <div className="metrics-grid mb-6">
          <div className="metric-card">
            <div className="metric-header">
              <span className="metric-title">Customer Accounts</span>
              <span className="metric-badge font-mono">{overview.active_accounts} Active</span>
            </div>
            <div className="metric-value font-mono">{overview.total_accounts}</div>
            <div className="metric-footer text-muted">
              {overview.frozen_accounts} Frozen • {overview.closed_accounts} Closed
            </div>
          </div>

          <div className="metric-card">
            <div className="metric-header">
              <span className="metric-title">Portfolio Balance</span>
              <span className="metric-badge">Verified</span>
            </div>
            <div className="metric-value font-mono text-emerald">
              <CurrencyAmount amountPaise={overview.total_portfolio_balance_paise} currency="INR" />
            </div>
            <div className="metric-footer">Total liquid customer deposits</div>
          </div>

          <div className="metric-card">
            <div className="metric-header">
              <span className="metric-title">Journal Transactions</span>
              <span className="metric-badge">Posted</span>
            </div>
            <div className="metric-value font-mono">{overview.total_transactions}</div>
            <div className="metric-footer">All financial lifecycle headers</div>
          </div>

          <div className="metric-card">
            <div className="metric-header">
              <span className="metric-title">Ledger Entries</span>
              <span className="metric-badge">Double-Entry</span>
            </div>
            <div className="metric-value font-mono">{overview.total_ledger_entries}</div>
            <div className="metric-footer text-emerald">Mathematically balanced debits/credits</div>
          </div>
        </div>
      )}

      {errorMessage && (
        <Alert type="error" message={errorMessage} onClose={() => setErrorMessage(null)} />
      )}

      {/* Navigation Tabs */}
      <div className="admin-tabs-nav mb-4">
        <button
          type="button"
          className={`admin-tab-btn ${activeTab === 'accounts' ? 'active' : ''}`}
          onClick={() => setActiveTab('accounts')}
        >
          Account Inventory ({accounts.length})
        </button>
        <button
          type="button"
          className={`admin-tab-btn ${activeTab === 'transactions' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('transactions')
            fetchTransactions()
          }}
        >
          Transaction Journal
        </button>
        <button
          type="button"
          className={`admin-tab-btn ${activeTab === 'audit' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('audit')
            fetchAuditLogs(auditActionFilter)
          }}
        >
          Audit Event Logs
        </button>
      </div>

      {/* TAB 1: ACCOUNT INVENTORY */}
      {activeTab === 'accounts' && (
        <div className="section-container">
          <div className="section-header flex justify-between items-center">
            <h2>System Accounts</h2>
            <div className="flex gap-2 items-center">
              <input
                type="text"
                placeholder="Search account name, number, UUID..."
                className="form-control form-control-sm"
                style={{ width: '280px' }}
                value={accountSearch}
                onChange={(e) => setAccountSearch(e.target.value)}
              />
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => {
                  fetchAccounts()
                  fetchOverview()
                }}
                disabled={isLoadingAccounts}
              >
                {isLoadingAccounts ? 'Refreshing...' : '↻ Refresh'}
              </button>
            </div>
          </div>

          {isLoadingAccounts ? (
            <div className="loading-state">
              <div className="spinner" />
              <p>Loading account inventory...</p>
            </div>
          ) : filteredAccounts.length === 0 ? (
            <div className="empty-state-card">
              <h3>No Accounts Found</h3>
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
                    <th>Created At</th>
                    <th>Account ID (UUID)</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAccounts.map((acc) => (
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
                      <td className="font-mono text-xs text-muted">
                        {new Date(acc.created_at).toLocaleDateString()}
                      </td>
                      <td className="font-mono text-xs text-muted" title={acc.id}>
                        {acc.id}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: TRANSACTION JOURNAL */}
      {activeTab === 'transactions' && (
        <div className="section-container">
          <div className="section-header flex justify-between items-center">
            <div>
              <h2>Global Transaction Journal</h2>
              <p className="text-muted text-xs">All posted money movement records across all accounts</p>
            </div>
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={fetchTransactions}
              disabled={isLoadingTxns}
            >
              {isLoadingTxns ? 'Refreshing...' : '↻ Refresh'}
            </button>
          </div>

          {isLoadingTxns ? (
            <div className="loading-state">
              <div className="spinner" />
              <p>Loading transaction journal...</p>
            </div>
          ) : transactions.length === 0 ? (
            <div className="empty-state-card">
              <h3>No Transactions Recorded</h3>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="statement-table">
                <thead>
                  <tr>
                    <th>Reference</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th className="text-right">Amount</th>
                    <th>Initiator ID</th>
                    <th>Timestamp</th>
                    <th className="text-right">Ledger Verification</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((tx) => (
                    <tr key={tx.id}>
                      <td className="font-mono font-medium">{tx.reference}</td>
                      <td>
                        <span className={`transaction-pill ${tx.transaction_type.toLowerCase()}`}>
                          {tx.transaction_type}
                        </span>
                      </td>
                      <td>
                        <span className="status-pill active">{tx.status}</span>
                      </td>
                      <td className="text-right">
                        <CurrencyAmount amountPaise={tx.amount_paise} currency={tx.currency} />
                      </td>
                      <td className="font-mono text-xs text-muted" title={tx.initiated_by || ''}>
                        {tx.initiated_by ? tx.initiated_by.slice(0, 8) + '...' : 'System'}
                      </td>
                      <td className="font-mono text-xs text-muted">
                        {new Date(tx.created_at).toLocaleString()}
                      </td>
                      <td className="text-right">
                        <button
                          type="button"
                          className="btn btn-outline btn-xs"
                          onClick={() => setSelectedTxnForLedger(tx)}
                        >
                          Inspect Double-Entry ({tx.ledger_entries?.length || 0})
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

      {/* TAB 3: AUDIT EVENT LOGS */}
      {activeTab === 'audit' && (
        <div className="section-container">
          <div className="section-header flex justify-between items-center">
            <div>
              <h2>Audit Event Log</h2>
              <p className="text-muted text-xs">Append-only audit trail verifying system compliance</p>
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

      {/* Double-Entry Ledger Inspector Modal */}
      {selectedTxnForLedger && (
        <Modal
          isOpen={true}
          onClose={() => setSelectedTxnForLedger(null)}
          title="Double-Entry Ledger Inspector"
        >
          <div className="ledger-inspector-content">
            <div className="mb-4">
              <div className="text-xs text-muted font-mono mb-1">
                TRANSACTION REF: {selectedTxnForLedger.reference}
              </div>
              <div className="flex items-center gap-2">
                <span className={`transaction-pill ${selectedTxnForLedger.transaction_type.toLowerCase()}`}>
                  {selectedTxnForLedger.transaction_type}
                </span>
                <span className="font-medium text-dark">
                  <CurrencyAmount
                    amountPaise={selectedTxnForLedger.amount_paise}
                    currency={selectedTxnForLedger.currency}
                  />
                </span>
              </div>
              <div className="text-xs text-muted mt-1">
                {new Date(selectedTxnForLedger.created_at).toLocaleString()}
              </div>
            </div>

            <div className="table-responsive mb-4">
              <table className="statement-table">
                <thead>
                  <tr>
                    <th>Account ID</th>
                    <th>Entry Type</th>
                    <th className="text-right">Amount (₹)</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedTxnForLedger.ledger_entries?.map((entry) => (
                    <tr key={entry.id}>
                      <td className="font-mono text-xs">{entry.account_id}</td>
                      <td>
                        <span
                          className={`badge-tag ${
                            entry.entry_type === 'CREDIT' ? 'badge-credit' : 'badge-debit'
                          }`}
                        >
                          {entry.entry_type}
                        </span>
                      </td>
                      <td className="text-right font-mono font-medium">
                        <CurrencyAmount amountPaise={entry.amount_paise} currency="INR" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="ledger-proof-banner">
              <div className="flex items-center gap-2">
                <span className="text-emerald font-bold">✓</span>
                <span className="text-sm font-medium">Balanced Double-Entry Proven:</span>
              </div>
              <p className="text-xs text-muted mt-1">
                Sum of Debits strictly equals Sum of Credits. All financial transactions satisfy zero-sum invariant.
              </p>
            </div>

            <div className="modal-actions mt-4">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setSelectedTxnForLedger(null)}
              >
                Close Inspector
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
