import { useState, useEffect, useCallback } from 'react'
import { CurrencyAmount } from './CurrencyAmount'
import { getAccountStatement } from '../api/transactions'
import type { AccountStatement, AccountWithMembership } from '../types/api'

interface StatementsViewerProps {
  accounts: AccountWithMembership[]
}

export function StatementsViewer({ accounts }: StatementsViewerProps) {
  const [selectedAccountId, setSelectedAccountId] = useState(accounts[0]?.id || '')
  const [statement, setStatement] = useState<AccountStatement | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const selectedAccount = accounts.find((a) => a.id === selectedAccountId) || accounts[0]

  const fetchStatement = useCallback(async (accountId: string) => {
    if (!accountId) return
    setIsLoading(true)
    setErrorMessage(null)
    try {
      const data = await getAccountStatement(accountId)
      setStatement(data)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load chronological account statement.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let isMounted = true
    if (!selectedAccountId) return

    Promise.resolve().then(() => {
      if (isMounted) setIsLoading(true)
    })

    getAccountStatement(selectedAccountId)
      .then((data) => {
        if (isMounted) setStatement(data)
      })
      .catch((err: any) => {
        if (isMounted) setErrorMessage(err.message || 'Failed to load chronological account statement.')
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })

    return () => {
      isMounted = false
    }
  }, [selectedAccountId])

  const handlePrint = () => {
    window.print()
  }

  return (
    <div className="statements-viewer-section">
      <div className="statements-header-bar">
        <div>
          <h2 className="section-title">Account Statements</h2>
          <p className="text-muted text-sm">
            Official chronological journal of double-entry ledger postings.
          </p>
        </div>

        <div className="statements-actions-group">
          <label htmlFor="statementAccountSelect" className="visually-hidden">Select Account</label>
          <select
            id="statementAccountSelect"
            className="form-control statement-account-select"
            value={selectedAccountId}
            onChange={(e) => setSelectedAccountId(e.target.value)}
          >
            {accounts.map((acc) => (
              <option key={acc.id} value={acc.id}>
                {acc.account_name} ({acc.account_number})
              </option>
            ))}
          </select>

          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={handlePrint}
            title="Print or Save as PDF"
          >
            🖨️ Print Statement
          </button>
        </div>
      </div>

      {/* Statement Meta Summary Card */}
      {selectedAccount && (
        <div className="statement-meta-banner">
          <div className="meta-item">
            <span className="meta-lbl">Account Number</span>
            <span className="meta-val font-mono">{selectedAccount.account_number}</span>
          </div>
          <div className="meta-item">
            <span className="meta-lbl">Account Type</span>
            <span className="meta-val">Standard Ledger Wallet</span>
          </div>
          <div className="meta-item">
            <span className="meta-lbl">Current Balance</span>
            <span className="meta-val font-bold text-primary">
              <CurrencyAmount
                amountPaise={statement?.balance_paise ?? selectedAccount.balance}
                currency={selectedAccount.currency}
              />
            </span>
          </div>
          <div className="meta-item">
            <span className="meta-lbl">Total Postings</span>
            <span className="meta-val font-semibold">{statement?.entries.length || 0}</span>
          </div>
        </div>
      )}

      {/* Postings Journal */}
      {errorMessage ? (
        <div className="table-error-state">
          <p>{errorMessage}</p>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={() => fetchStatement(selectedAccountId)}
          >
            Retry
          </button>
        </div>
      ) : isLoading ? (
        <div className="loading-state">
          <div className="spinner" />
          <p>Compiling immutable statement from double-entry ledger...</p>
        </div>
      ) : !statement || statement.entries.length === 0 ? (
        <div className="table-empty-state">
          <div className="empty-state-icon">📑</div>
          <h4>No Entries Posted Yet</h4>
          <p className="text-muted text-sm">
            This account currently has no double-entry ledger postings. Execute a deposit or transfer to begin transaction activity.
          </p>
        </div>
      ) : (
        <div className="table-responsive">
          <table className="banking-table statement-table">
            <thead>
              <tr>
                <th>Posting Timestamp</th>
                <th>Transaction Ref</th>
                <th>Description</th>
                <th>Type</th>
                <th>Direction</th>
                <th className="text-right">Paise Amount</th>
              </tr>
            </thead>
            <tbody>
              {statement.entries.map((entry) => (
                <tr key={entry.id}>
                  <td className="text-sm font-mono text-muted">
                    {new Date(entry.created_at).toLocaleString('en-IN', {
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="font-mono text-xs font-semibold">{entry.reference}</td>
                  <td className="text-sm">{entry.description || 'Ledger Posting'}</td>
                  <td>
                    <span className={`tx-type-badge tx-type-${entry.transaction_type.toLowerCase()}`}>
                      {entry.transaction_type}
                    </span>
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        entry.entry_type === 'CREDIT' ? 'badge-owner' : 'badge-operator'
                      }`}
                    >
                      {entry.entry_type}
                    </span>
                  </td>
                  <td
                    className={`text-right font-mono font-medium ${
                      entry.entry_type === 'CREDIT' ? 'amount-credit' : 'amount-debit'
                    }`}
                  >
                    {entry.entry_type === 'CREDIT' ? '+' : '-'}
                    <CurrencyAmount amountPaise={entry.amount_paise} currency={statement.currency} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
