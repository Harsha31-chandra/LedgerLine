import { useState, useMemo } from 'react'
import { CurrencyAmount } from './CurrencyAmount'
import { Modal } from './Modal'
import type { Transaction, TransactionType } from '../types/api'

interface RecentTransactionsTableProps {
  transactions: Transaction[]
  isLoading: boolean
  errorMessage: string | null
  onRefresh: () => void
  userAccountIds?: string[]
}

export function RecentTransactionsTable({
  transactions,
  isLoading,
  errorMessage,
  onRefresh,
  userAccountIds = [],
}: RecentTransactionsTableProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<'ALL' | TransactionType>('ALL')
  const [currentPage, setCurrentPage] = useState(1)
  const [selectedTx, setSelectedTx] = useState<Transaction | null>(null)
  const pageSize = 10

  const filteredTransactions = useMemo(() => {
    return transactions.filter((tx) => {
      // Filter by type
      if (typeFilter !== 'ALL' && tx.transaction_type !== typeFilter) {
        return false
      }
      // Filter by search query (reference or description)
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim()
        const refMatch = tx.reference.toLowerCase().includes(q)
        const descMatch = (tx.description || '').toLowerCase().includes(q)
        if (!refMatch && !descMatch) return false
      }
      return true
    })
  }, [transactions, typeFilter, searchQuery])

  // Pagination calculation
  const totalPages = Math.ceil(filteredTransactions.length / pageSize) || 1
  const paginatedTransactions = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredTransactions.slice(start, start + pageSize)
  }, [filteredTransactions, currentPage, pageSize])

  // Helper to determine if transaction was a credit or debit for the viewer's accounts
  const getTransactionDirection = (tx: Transaction): 'credit' | 'debit' | 'neutral' => {
    if (tx.transaction_type === 'DEPOSIT') return 'credit'
    if (tx.transaction_type === 'WITHDRAWAL') return 'debit'

    // For transfers: check if user account was debited or credited
    if (userAccountIds.length > 0) {
      const userEntries = tx.ledger_entries.filter((e) => userAccountIds.includes(e.account_id))
      const hasCredit = userEntries.some((e) => e.entry_type === 'CREDIT')
      const hasDebit = userEntries.some((e) => e.entry_type === 'DEBIT')
      if (hasCredit && !hasDebit) return 'credit'
      if (hasDebit && !hasCredit) return 'debit'
    }
    return 'neutral'
  }

  return (
    <div className="transactions-table-container">
      {/* Table Header Controls */}
      <div className="table-controls-bar">
        <div className="search-filter-group">
          <div className="search-input-wrapper">
            <span className="search-icon" aria-hidden="true">🔍</span>
            <input
              type="text"
              placeholder="Search by reference or note..."
              className="table-search-input"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value)
                setCurrentPage(1)
              }}
            />
            {searchQuery && (
              <button
                type="button"
                className="search-clear-btn"
                onClick={() => setSearchQuery('')}
                aria-label="Clear search"
              >
                ×
              </button>
            )}
          </div>

          <div className="filter-select-wrapper">
            <label htmlFor="typeFilterSelect" className="visually-hidden">Filter by type</label>
            <select
              id="typeFilterSelect"
              className="table-filter-select"
              value={typeFilter}
              onChange={(e) => {
                setTypeFilter(e.target.value as 'ALL' | TransactionType)
                setCurrentPage(1)
              }}
            >
              <option value="ALL">All Types</option>
              <option value="DEPOSIT">Deposits</option>
              <option value="WITHDRAWAL">Withdrawals</option>
              <option value="TRANSFER">Transfers</option>
            </select>
          </div>
        </div>

        <button
          type="button"
          className="btn btn-outline btn-sm table-refresh-btn"
          onClick={onRefresh}
          disabled={isLoading}
        >
          {isLoading ? 'Refreshing...' : '↻ Refresh Data'}
        </button>
      </div>

      {/* Table Viewport */}
      {errorMessage ? (
        <div className="table-error-state">
          <span className="error-icon">⚠️</span>
          <p>{errorMessage}</p>
          <button type="button" className="btn btn-outline btn-sm" onClick={onRefresh}>
            Try Again
          </button>
        </div>
      ) : isLoading ? (
        <div className="table-skeleton-container" aria-busy="true">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="table-skeleton-row">
              <div className="skeleton-bar w-20" />
              <div className="skeleton-bar w-30" />
              <div className="skeleton-bar w-15" />
              <div className="skeleton-bar w-15" />
              <div className="skeleton-bar w-20" />
            </div>
          ))}
        </div>
      ) : paginatedTransactions.length === 0 ? (
        <div className="table-empty-state">
          <div className="empty-state-icon">📋</div>
          <h4>No Transactions Found</h4>
          <p className="text-muted text-sm">
            {searchQuery || typeFilter !== 'ALL'
              ? 'No transactions matched your current search filters. Try resetting filters.'
              : 'You have not executed any transactions yet. Use Quick Actions above to deposit or transfer funds.'}
          </p>
          {(searchQuery || typeFilter !== 'ALL') && (
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={() => {
                setSearchQuery('')
                setTypeFilter('ALL')
              }}
            >
              Reset Filters
            </button>
          )}
        </div>
      ) : (
        <div className="table-responsive">
          <table className="banking-table">
            <thead>
              <tr>
                <th>Reference</th>
                <th>Date & Time</th>
                <th>Description</th>
                <th>Type</th>
                <th className="text-right">Amount</th>
                <th>Status</th>
                <th className="text-center">Action</th>
              </tr>
            </thead>
            <tbody>
              {paginatedTransactions.map((tx) => {
                const direction = getTransactionDirection(tx)
                const dateStr = new Date(tx.created_at).toLocaleString('en-IN', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })

                return (
                  <tr key={tx.id} className="table-row-interactive">
                    <td className="font-mono text-sm font-semibold">
                      <span className="tx-reference-tag" title={tx.reference}>
                        {tx.reference.length > 20
                          ? `${tx.reference.slice(0, 10)}...${tx.reference.slice(-8)}`
                          : tx.reference}
                      </span>
                    </td>
                    <td className="text-sm text-muted">{dateStr}</td>
                    <td className="text-sm">
                      <span className="tx-description" title={tx.description || undefined}>
                        {tx.description || 'Standard transaction'}
                      </span>
                    </td>
                    <td>
                      <span className={`tx-type-badge tx-type-${tx.transaction_type.toLowerCase()}`}>
                        {tx.transaction_type === 'DEPOSIT' && '📥 '}
                        {tx.transaction_type === 'WITHDRAWAL' && '📤 '}
                        {tx.transaction_type === 'TRANSFER' && '⇄ '}
                        {tx.transaction_type}
                      </span>
                    </td>
                    <td className="text-right font-medium">
                      <span
                        className={`amount-display ${
                          direction === 'credit'
                            ? 'amount-credit'
                            : direction === 'debit'
                            ? 'amount-debit'
                            : ''
                        }`}
                      >
                        {direction === 'credit' && '+'}
                        {direction === 'debit' && '-'}
                        <CurrencyAmount amountPaise={tx.amount_paise} currency={tx.currency} />
                      </span>
                    </td>
                    <td>
                      <span className={`status-pill status-${tx.status.toLowerCase()}`}>
                        {tx.status}
                      </span>
                    </td>
                    <td className="text-center">
                      <button
                        type="button"
                        className="btn btn-outline btn-xs inspect-btn"
                        onClick={() => setSelectedTx(tx)}
                        title="Inspect Double-Entry Ledger Entries"
                      >
                        Ledger ↗
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination Footer */}
      {!isLoading && filteredTransactions.length > pageSize && (
        <div className="table-pagination-bar">
          <span className="pagination-info">
            Showing {(currentPage - 1) * pageSize + 1}–
            {Math.min(currentPage * pageSize, filteredTransactions.length)} of{' '}
            {filteredTransactions.length} postings
          </span>
          <div className="pagination-controls">
            <button
              type="button"
              className="btn btn-outline btn-xs"
              onClick={() => setCurrentPage((p) => Math.max(p - 1, 1))}
              disabled={currentPage === 1}
            >
              ← Previous
            </button>
            <span className="pagination-current-page">
              Page {currentPage} of {totalPages}
            </span>
            <button
              type="button"
              className="btn btn-outline btn-xs"
              onClick={() => setCurrentPage((p) => Math.min(p + 1, totalPages))}
              disabled={currentPage === totalPages}
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {/* Transaction Double-Entry Inspection Modal */}
      {selectedTx && (
        <Modal
          isOpen={Boolean(selectedTx)}
          onClose={() => setSelectedTx(null)}
          title={`Transaction Audit: ${selectedTx.reference}`}
        >
          <div className="tx-detail-modal-body">
            <div className="tx-modal-summary">
              <div className="summary-col">
                <span className="summary-label">Transaction Type</span>
                <span className="summary-val font-semibold">{selectedTx.transaction_type}</span>
              </div>
              <div className="summary-col">
                <span className="summary-label">Total Amount</span>
                <span className="summary-val font-semibold text-primary">
                  <CurrencyAmount
                    amountPaise={selectedTx.amount_paise}
                    currency={selectedTx.currency}
                  />
                </span>
              </div>
              <div className="summary-col">
                <span className="summary-label">Status</span>
                <span className="summary-val font-semibold">{selectedTx.status}</span>
              </div>
              <div className="summary-col">
                <span className="summary-label">Timestamp</span>
                <span className="summary-val font-mono text-xs">
                  {new Date(selectedTx.created_at).toISOString()}
                </span>
              </div>
            </div>

            {selectedTx.description && (
              <div className="tx-description-box">
                <strong>Description:</strong> {selectedTx.description}
              </div>
            )}

            <h4 style={{ margin: '1.25rem 0 0.5rem', color: '#1E3A8A' }}>
              Authoritative Double-Entry Ledger Postings
            </h4>
            <div className="table-responsive">
              <table className="banking-table text-sm">
                <thead>
                  <tr>
                    <th>Account ID</th>
                    <th>Entry Type</th>
                    <th className="text-right">Paise Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedTx.ledger_entries.map((entry) => (
                    <tr key={entry.id}>
                      <td className="font-mono text-xs text-muted">{entry.account_id}</td>
                      <td>
                        <span
                          className={`badge ${
                            entry.entry_type === 'DEBIT' ? 'badge-operator' : 'badge-owner'
                          }`}
                        >
                          {entry.entry_type}
                        </span>
                      </td>
                      <td className="text-right font-mono font-medium">
                        <CurrencyAmount amountPaise={entry.amount_paise} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1.5rem' }}>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setSelectedTx(null)}
              >
                Close Audit View
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
