import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getAccount, updateAccount, updateAccountStatus } from '../api/accounts'
import {
  depositFunds,
  getAccountStatement,
  getTransaction,
  transferFunds,
  withdrawFunds,
} from '../api/transactions'
import { Alert } from '../components/Alert'
import { CurrencyAmount } from '../components/CurrencyAmount'
import { Modal } from '../components/Modal'
import { RoleBadge } from '../components/RoleBadge'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../hooks/useAuth'
import type {
  AccountStatus,
  AccountStatement,
  AccountWithMembership,
  Transaction,
} from '../types/api'
import { formatPaise, parseRupeesToPaise } from '../utils/currency'

export function AccountDetailPage() {
  const { accountId } = useParams<{ accountId: string }>()
  const { user } = useAuth()

  const [account, setAccount] = useState<AccountWithMembership | null>(null)
  const [statement, setStatement] = useState<AccountStatement | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  // Modals state
  const [activeModal, setActiveModal] = useState<
    'deposit' | 'withdraw' | 'transfer' | 'editName' | 'status' | 'viewTx' | null
  >(null)

  // Transaction inspection modal state
  const [selectedTx, setSelectedTx] = useState<Transaction | null>(null)
  const [isLoadingTx, setIsLoadingTx] = useState(false)

  // Form states
  const [formAmountRupees, setFormAmountRupees] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formDestinationId, setFormDestinationId] = useState('')
  const [formNewName, setFormNewName] = useState('')
  const [formNewStatus, setFormNewStatus] = useState<AccountStatus>('ACTIVE')

  // In-flight and error states for active operation
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [opError, setOpError] = useState<string | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState<string>('')

  const loadData = useCallback(async () => {
    if (!accountId) return
    setIsLoading(true)
    setErrorMessage(null)
    try {
      const [accData, stmtData] = await Promise.all([
        getAccount(accountId),
        getAccountStatement(accountId),
      ])
      setAccount(accData)
      setStatement(stmtData)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load account details or statement.')
    } finally {
      setIsLoading(false)
    }
  }, [accountId])

  useEffect(() => {
    if (!accountId) return
    let isMounted = true
    Promise.all([getAccount(accountId), getAccountStatement(accountId)])
      .then(([accData, stmtData]) => {
        if (isMounted) {
          setAccount(accData)
          setStatement(stmtData)
        }
      })
      .catch((err: any) => {
        if (isMounted) {
          setErrorMessage(err.message || 'Failed to load account details or statement.')
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
  }, [accountId])

  // Open modal with freshly initialized idempotency key
  const openModal = (modalType: 'deposit' | 'withdraw' | 'transfer' | 'editName' | 'status') => {
    setOpError(null)
    setFormAmountRupees('')
    setFormDescription('')
    setFormDestinationId('')
    if (account) {
      setFormNewName(account.account_name)
      setFormNewStatus(account.status)
    }
    // Generate fresh idempotency key for this new user operation
    setIdempotencyKey(crypto.randomUUID())
    setActiveModal(modalType)
  }

  const closeModal = () => {
    if (isSubmitting) return // Prevent closing mid-transaction
    setActiveModal(null)
    setOpError(null)
  }

  // Handle Deposit
  const handleDepositSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!account) return

    const amountPaise = parseRupeesToPaise(formAmountRupees)
    if (amountPaise <= 0) {
      setOpError('Please enter a valid positive amount.')
      return
    }

    setIsSubmitting(true)
    setOpError(null)
    try {
      await depositFunds(
        {
          account_id: account.id,
          amount_paise: amountPaise,
          description: formDescription.trim() || undefined,
        },
        idempotencyKey,
      )
      setSuccessMessage(`Successfully deposited ${formatPaise(amountPaise, account.currency)}.`)
      closeModal()
      await loadData()
    } catch (err: any) {
      // Keep same idempotencyKey for retry!
      setOpError(err.message || 'Deposit failed.')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Handle Withdrawal
  const handleWithdrawalSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!account) return

    const amountPaise = parseRupeesToPaise(formAmountRupees)
    if (amountPaise <= 0) {
      setOpError('Please enter a valid positive amount.')
      return
    }
    if (amountPaise > account.balance) {
      setOpError(`Insufficient balance. Current balance is ${formatPaise(account.balance, account.currency)}.`)
      return
    }

    setIsSubmitting(true)
    setOpError(null)
    try {
      await withdrawFunds(
        {
          account_id: account.id,
          amount_paise: amountPaise,
          description: formDescription.trim() || undefined,
        },
        idempotencyKey,
      )
      setSuccessMessage(`Successfully withdrawn ${formatPaise(amountPaise, account.currency)}.`)
      closeModal()
      await loadData()
    } catch (err: any) {
      // Keep same idempotencyKey for retry!
      setOpError(err.message || 'Withdrawal failed.')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Handle Transfer
  const handleTransferSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!account) return

    const destId = formDestinationId.trim()
    if (!destId) {
      setOpError('Please enter the destination Account ID.')
      return
    }
    if (destId.toLowerCase() === account.id.toLowerCase()) {
      setOpError('Source and destination accounts cannot be identical.')
      return
    }

    const amountPaise = parseRupeesToPaise(formAmountRupees)
    if (amountPaise <= 0) {
      setOpError('Please enter a valid positive amount.')
      return
    }
    if (amountPaise > account.balance) {
      setOpError(`Insufficient funds. Current balance is ${formatPaise(account.balance, account.currency)}.`)
      return
    }

    setIsSubmitting(true)
    setOpError(null)
    try {
      await transferFunds(
        {
          source_account_id: account.id,
          destination_account_id: destId,
          amount_paise: amountPaise,
          description: formDescription.trim() || undefined,
        },
        idempotencyKey,
      )
      setSuccessMessage(`Successfully transferred ${formatPaise(amountPaise, account.currency)}.`)
      closeModal()
      await loadData()
    } catch (err: any) {
      // Keep same idempotencyKey for retry!
      setOpError(err.message || 'Transfer failed.')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Handle Update Name (Owner only)
  const handleUpdateNameSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!account) return

    if (!formNewName.trim()) {
      setOpError('Account name cannot be empty.')
      return
    }

    setIsSubmitting(true)
    setOpError(null)
    try {
      await updateAccount(account.id, { account_name: formNewName.trim() })
      setSuccessMessage('Account name updated successfully.')
      closeModal()
      await loadData()
    } catch (err: any) {
      setOpError(err.message || 'Failed to update account name.')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Handle Update Status (Admin only)
  const handleUpdateStatusSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!account) return

    setIsSubmitting(true)
    setOpError(null)
    try {
      await updateAccountStatus(account.id, { status: formNewStatus })
      setSuccessMessage(`Account status changed to ${formNewStatus}.`)
      closeModal()
      await loadData()
    } catch (err: any) {
      setOpError(err.message || 'Failed to update account status.')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Inspect Transaction Double-Entry Journal
  const handleInspectTx = async (txId: string) => {
    setIsLoadingTx(true)
    setSelectedTx(null)
    setActiveModal('viewTx')
    try {
      const tx = await getTransaction(txId)
      setSelectedTx(tx)
    } catch (err: any) {
      setOpError(err.message || 'Failed to retrieve transaction details.')
    } finally {
      setIsLoadingTx(false)
    }
  }

  const isAccountActive = account?.status === 'ACTIVE'
  const isOwner = account?.membership_role === 'OWNER'
  const isViewer = account?.membership_role === 'VIEWER'
  const isAdmin = user?.role === 'ADMIN'
  const canOperate = isAccountActive && !isViewer

  if (isLoading) {
    return (
      <div className="page-container">
        <div className="loading-state">
          <div className="spinner" />
          <p>Loading financial account details and statement...</p>
        </div>
      </div>
    )
  }

  if (errorMessage || !account) {
    return (
      <div className="page-container">
        <Alert type="error" message={errorMessage || 'Account not found or access denied.'} />
        <div className="mt-4">
          <Link to="/" className="btn btn-secondary">
            ← Back to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page-container">
      {/* Navigation Breadcrumb */}
      <div className="breadcrumb">
        <Link to="/" className="text-link">
          Dashboard
        </Link>
        <span className="breadcrumb-separator">/</span>
        <span className="breadcrumb-current">{account.account_name}</span>
      </div>

      {successMessage && (
        <Alert
          type="success"
          message={successMessage}
          onClose={() => setSuccessMessage(null)}
        />
      )}

      {/* Account Overview Header */}
      <div className="account-hero-card">
        <div className="account-hero-main">
          <div className="account-title-section">
            <h1 className="account-name">{account.account_name}</h1>
            <div className="account-badges">
              <span className="account-id-badge" title="Account Number">
                {account.account_number}
              </span>
              <StatusBadge status={account.status} />
              <RoleBadge role={account.membership_role} type="membership" />
            </div>
          </div>

          <div className="account-balance-section">
            <span className="balance-caption">Verified Ledger Balance</span>
            <div className="balance-hero">
              <CurrencyAmount
                amountPaise={account.balance}
                currency={account.currency}
              />
            </div>
          </div>
        </div>

        {/* Status Warning if Inactive */}
        {!isAccountActive && (
          <div className="account-status-alert">
            <span className="status-alert-icon">⚠️</span>
            <span>
              This account is currently <strong>{account.status}</strong>. Transactions cannot be processed
              until the status is transitioned to ACTIVE.
            </span>
          </div>
        )}

        {/* Action Controls */}
        <div className="account-action-toolbar">
          <div className="financial-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => openModal('deposit')}
              disabled={!canOperate}
              title={!canOperate ? 'Account must be ACTIVE with OPERATE privileges' : 'Deposit funds'}
            >
              + Deposit
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => openModal('withdraw')}
              disabled={!canOperate || account.balance <= 0}
              title={
                !canOperate
                  ? 'Account must be ACTIVE with OPERATE privileges'
                  : account.balance <= 0
                    ? 'Account has no funds to withdraw'
                    : 'Withdraw funds'
              }
            >
              - Withdraw
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => openModal('transfer')}
              disabled={!canOperate || account.balance <= 0}
              title={
                !canOperate
                  ? 'Account must be ACTIVE with OPERATE privileges'
                  : account.balance <= 0
                    ? 'Account has no funds to transfer'
                    : 'Transfer funds'
              }
            >
              ⇄ Transfer
            </button>
          </div>

          <div className="management-actions">
            {(isOwner || isAdmin) && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => openModal('editName')}
              >
                Rename
              </button>
            )}
            {isAdmin && (
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => openModal('status')}
              >
                Change Status
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Account Statement Section */}
      <div className="section-container mt-8">
        <div className="section-header">
          <div>
            <h2>Chronological Account Statement</h2>
            <p className="section-subtitle">
              Immutable double-entry ledger postings for this account
            </p>
          </div>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={loadData}
          >
            ↻ Refresh Statement
          </button>
        </div>

        {!statement || statement.entries.length === 0 ? (
          <div className="empty-state-card">
            <div className="empty-icon">📜</div>
            <h3>No Statement Entries</h3>
            <p className="text-muted">
              There have been no posted transactions on this account yet. Deposit funds to initiate the
              ledger journal.
            </p>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="statement-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Reference</th>
                  <th>Transaction Type</th>
                  <th>Entry Type</th>
                  <th className="text-right">Amount</th>
                  <th>Description</th>
                  <th className="text-center">Audit</th>
                </tr>
              </thead>
              <tbody>
                {statement.entries.map((entry) => {
                  const isCredit = entry.entry_type === 'CREDIT'
                  return (
                    <tr key={entry.id} className="statement-row">
                      <td className="text-nowrap text-muted font-mono">
                        {new Date(entry.created_at).toLocaleString('en-IN', {
                          dateStyle: 'short',
                          timeStyle: 'medium',
                        })}
                      </td>
                      <td className="font-mono text-dark font-medium">{entry.reference}</td>
                      <td>
                        <span className="type-badge">{entry.transaction_type}</span>
                      </td>
                      <td>
                        <span className={`entry-badge ${isCredit ? 'credit' : 'debit'}`}>
                          {entry.entry_type}
                        </span>
                      </td>
                      <td className="text-right">
                        <CurrencyAmount
                          amountPaise={entry.amount_paise}
                          currency={account.currency}
                          showSign={true}
                        />
                      </td>
                      <td className="text-muted">{entry.description || '—'}</td>
                      <td className="text-center">
                        <button
                          type="button"
                          className="btn btn-outline btn-xs"
                          onClick={() => handleInspectTx(entry.transaction_id)}
                          title="Inspect balanced double-entry ledger postings"
                        >
                          Inspect
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal: Deposit */}
      <Modal
        isOpen={activeModal === 'deposit'}
        onClose={closeModal}
        title={`Deposit into ${account.account_name}`}
      >
        <form onSubmit={handleDepositSubmit}>
          {opError && <Alert type="error" message={opError} onClose={() => setOpError(null)} />}

          <div className="form-group">
            <label htmlFor="deposit-amount">Amount (in {account.currency})</label>
            <div className="input-prefix-container">
              <span className="input-prefix">₹</span>
              <input
                id="deposit-amount"
                type="number"
                step="0.01"
                min="0.01"
                required
                className="form-control pl-8"
                placeholder="0.00"
                value={formAmountRupees}
                onChange={(e) => setFormAmountRupees(e.target.value)}
                disabled={isSubmitting}
                autoFocus
              />
            </div>
            <span className="field-hint">
              Deposited from system clearing into customer account.
            </span>
          </div>

          <div className="form-group">
            <label htmlFor="deposit-desc">Description (optional)</label>
            <input
              id="deposit-desc"
              type="text"
              maxLength={255}
              className="form-control"
              placeholder="e.g. Salary deposit, Initial funding"
              value={formDescription}
              onChange={(e) => setFormDescription(e.target.value)}
              disabled={isSubmitting}
            />
          </div>

          <div className="idempotency-badge">
            <span className="text-muted text-xs">
              Idempotency Key: <code className="font-mono">{idempotencyKey}</code>
            </span>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeModal}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Posting Deposit...' : 'Confirm Deposit'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Withdraw */}
      <Modal
        isOpen={activeModal === 'withdraw'}
        onClose={closeModal}
        title={`Withdraw from ${account.account_name}`}
      >
        <form onSubmit={handleWithdrawalSubmit}>
          {opError && <Alert type="error" message={opError} onClose={() => setOpError(null)} />}

          <div className="form-group">
            <label htmlFor="withdraw-amount">Amount (in {account.currency})</label>
            <div className="input-prefix-container">
              <span className="input-prefix">₹</span>
              <input
                id="withdraw-amount"
                type="number"
                step="0.01"
                min="0.01"
                required
                className="form-control pl-8"
                placeholder="0.00"
                value={formAmountRupees}
                onChange={(e) => setFormAmountRupees(e.target.value)}
                disabled={isSubmitting}
                autoFocus
              />
            </div>
            <span className="field-hint">
              Available Balance: {formatPaise(account.balance, account.currency)}
            </span>
          </div>

          <div className="form-group">
            <label htmlFor="withdraw-desc">Description (optional)</label>
            <input
              id="withdraw-desc"
              type="text"
              maxLength={255}
              className="form-control"
              placeholder="e.g. ATM withdrawal, Vendor invoice"
              value={formDescription}
              onChange={(e) => setFormDescription(e.target.value)}
              disabled={isSubmitting}
            />
          </div>

          <div className="idempotency-badge">
            <span className="text-muted text-xs">
              Idempotency Key: <code className="font-mono">{idempotencyKey}</code>
            </span>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeModal}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Posting Withdrawal...' : 'Confirm Withdrawal'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Transfer */}
      <Modal
        isOpen={activeModal === 'transfer'}
        onClose={closeModal}
        title={`Transfer from ${account.account_name}`}
      >
        <form onSubmit={handleTransferSubmit}>
          {opError && <Alert type="error" message={opError} onClose={() => setOpError(null)} />}

          <div className="form-group">
            <label htmlFor="transfer-dest">Destination Account UUID</label>
            <input
              id="transfer-dest"
              type="text"
              required
              className="form-control font-mono"
              placeholder="e.g. a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
              value={formDestinationId}
              onChange={(e) => setFormDestinationId(e.target.value)}
              disabled={isSubmitting}
              autoFocus
            />
            <span className="field-hint">
              Target account must be ACTIVE and accept {account.currency}.
            </span>
          </div>

          <div className="form-group">
            <label htmlFor="transfer-amount">Amount (in {account.currency})</label>
            <div className="input-prefix-container">
              <span className="input-prefix">₹</span>
              <input
                id="transfer-amount"
                type="number"
                step="0.01"
                min="0.01"
                required
                className="form-control pl-8"
                placeholder="0.00"
                value={formAmountRupees}
                onChange={(e) => setFormAmountRupees(e.target.value)}
                disabled={isSubmitting}
              />
            </div>
            <span className="field-hint">
              Available: {formatPaise(account.balance, account.currency)}
            </span>
          </div>

          <div className="form-group">
            <label htmlFor="transfer-desc">Description (optional)</label>
            <input
              id="transfer-desc"
              type="text"
              maxLength={255}
              className="form-control"
              placeholder="e.g. P2P Payment, Invoice settlement"
              value={formDescription}
              onChange={(e) => setFormDescription(e.target.value)}
              disabled={isSubmitting}
            />
          </div>

          <div className="idempotency-badge">
            <span className="text-muted text-xs">
              Idempotency Key: <code className="font-mono">{idempotencyKey}</code>
            </span>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeModal}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Executing Transfer...' : 'Execute Transfer'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Edit Name */}
      <Modal
        isOpen={activeModal === 'editName'}
        onClose={closeModal}
        title="Rename Account"
      >
        <form onSubmit={handleUpdateNameSubmit}>
          {opError && <Alert type="error" message={opError} onClose={() => setOpError(null)} />}

          <div className="form-group">
            <label htmlFor="edit-name">Account Name</label>
            <input
              id="edit-name"
              type="text"
              required
              maxLength={100}
              className="form-control"
              value={formNewName}
              onChange={(e) => setFormNewName(e.target.value)}
              disabled={isSubmitting}
              autoFocus
            />
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeModal}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Saving...' : 'Save Name'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Admin Change Status */}
      <Modal
        isOpen={activeModal === 'status'}
        onClose={closeModal}
        title="Administrative Account Lifecycle Status"
      >
        <form onSubmit={handleUpdateStatusSubmit}>
          {opError && <Alert type="error" message={opError} onClose={() => setOpError(null)} />}

          <div className="form-group">
            <label htmlFor="select-status">Account Status</label>
            <select
              id="select-status"
              className="form-control"
              value={formNewStatus}
              onChange={(e) => setFormNewStatus(e.target.value as AccountStatus)}
              disabled={isSubmitting}
            >
              <option value="ACTIVE">ACTIVE — Normal deposit, withdrawal, and transfer operations</option>
              <option value="FROZEN">FROZEN — Operations blocked; account preserved</option>
              <option value="CLOSED">CLOSED — Permanently closed</option>
            </select>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeModal}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Updating Status...' : 'Apply Status Transition'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Double-Entry Ledger Inspection */}
      <Modal
        isOpen={activeModal === 'viewTx'}
        onClose={() => setActiveModal(null)}
        title="Double-Entry Ledger Audit"
      >
        {isLoadingTx ? (
          <div className="loading-state">
            <div className="spinner" />
            <p>Fetching ledger entry journal...</p>
          </div>
        ) : selectedTx ? (
          <div className="audit-detail">
            <div className="audit-summary-grid">
              <div>
                <span className="text-muted text-xs">Reference:</span>
                <p className="font-mono font-medium">{selectedTx.reference}</p>
              </div>
              <div>
                <span className="text-muted text-xs">Transaction Type:</span>
                <p className="font-medium">{selectedTx.transaction_type}</p>
              </div>
              <div>
                <span className="text-muted text-xs">Status:</span>
                <div>
                  <StatusBadge status={selectedTx.status} />
                </div>
              </div>
              <div>
                <span className="text-muted text-xs">Total Amount:</span>
                <p className="font-medium">
                  <CurrencyAmount
                    amountPaise={selectedTx.amount_paise}
                    currency={selectedTx.currency}
                  />
                </p>
              </div>
            </div>

            <h4 className="mt-4 mb-2 font-medium">Balanced Ledger Journal Entries:</h4>
            <div className="table-responsive">
              <table className="statement-table text-sm">
                <thead>
                  <tr>
                    <th>Entry ID</th>
                    <th>Account ID</th>
                    <th>Type</th>
                    <th className="text-right">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedTx.ledger_entries.map((entry) => (
                    <tr key={entry.id}>
                      <td className="font-mono text-xs">{entry.id.slice(0, 8)}...</td>
                      <td className="font-mono text-xs">{entry.account_id}</td>
                      <td>
                        <span
                          className={`entry-badge ${entry.entry_type === 'CREDIT' ? 'credit' : 'debit'}`}
                        >
                          {entry.entry_type}
                        </span>
                      </td>
                      <td className="text-right">
                        <CurrencyAmount
                          amountPaise={entry.amount_paise}
                          currency={selectedTx.currency}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="field-hint mt-2">
              Invariant: Total Debits == Total Credits. Immutable double-entry posting.
            </p>
          </div>
        ) : (
          <p className="text-muted">Unable to load transaction details.</p>
        )}
      </Modal>
    </div>
  )
}
