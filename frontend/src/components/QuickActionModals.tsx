import { useState, type FormEvent } from 'react'
import { Modal } from './Modal'
import { Alert } from './Alert'
import { depositFunds, withdrawFunds, transferFunds } from '../api/transactions'
import type { AccountWithMembership } from '../types/api'
import { parseRupeesToPaise } from '../utils/currency'

interface QuickActionModalsProps {
  activeModal: 'deposit' | 'withdraw' | 'transfer' | null
  onClose: () => void
  accounts: AccountWithMembership[]
  onSuccess: (message: string) => void
}

export function QuickActionModals({
  activeModal,
  onClose,
  accounts,
  onSuccess,
}: QuickActionModalsProps) {
  const [selectedAccountId, setSelectedAccountId] = useState(accounts[0]?.id || '')
  const [destinationAccountId, setDestinationAccountId] = useState('')
  const [amountRupees, setAmountRupees] = useState('')
  const [description, setDescription] = useState('')
  const [isConfirming, setIsConfirming] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const selectedAccount = accounts.find((a) => a.id === selectedAccountId) || accounts[0]
  const amountPaise = parseRupeesToPaise(amountRupees)

  const handleReset = () => {
    setAmountRupees('')
    setDescription('')
    setDestinationAccountId('')
    setIsConfirming(false)
    setErrorMessage(null)
    setIsSubmitting(false)
    onClose()
  }

  const handleQuickAmount = (rupees: number) => {
    setAmountRupees(rupees.toString())
  }

  const handleInitialSubmit = (e: FormEvent) => {
    e.preventDefault()
    setErrorMessage(null)

    if (!selectedAccount) {
      setErrorMessage('Please select a valid financial account.')
      return
    }

    if (amountPaise <= 0) {
      setErrorMessage('Please enter a valid positive amount greater than zero.')
      return
    }

    if (activeModal === 'withdraw' && amountPaise > selectedAccount.balance) {
      setErrorMessage(
        `Insufficient funds. Available balance is ₹${(selectedAccount.balance / 100).toLocaleString('en-IN')}`,
      )
      return
    }

    if (activeModal === 'transfer') {
      if (!destinationAccountId.trim()) {
        setErrorMessage('Destination account identifier or account number is required.')
        return
      }
      if (destinationAccountId.trim() === selectedAccount.id || destinationAccountId.trim() === selectedAccount.account_number) {
        setErrorMessage('Source and destination accounts must be distinct.')
        return
      }
      if (amountPaise > selectedAccount.balance) {
        setErrorMessage(
          `Insufficient funds for transfer. Available balance is ₹${(selectedAccount.balance / 100).toLocaleString('en-IN')}`,
        )
        return
      }
    }

    setIsConfirming(true)
  }

  const handleExecuteOperation = async () => {
    setIsSubmitting(true)
    setErrorMessage(null)

    const idempotencyKey = `qa-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`

    try {
      if (activeModal === 'deposit') {
        await depositFunds(
          {
            account_id: selectedAccount.id,
            amount_paise: amountPaise,
            description: description.trim() || 'Online Deposit via Dashboard',
          },
          idempotencyKey,
        )
        onSuccess(`Successfully deposited ₹${amountRupees} into ${selectedAccount.account_name}.`)
        handleReset()
      } else if (activeModal === 'withdraw') {
        await withdrawFunds(
          {
            account_id: selectedAccount.id,
            amount_paise: amountPaise,
            description: description.trim() || 'Withdrawal via Dashboard',
          },
          idempotencyKey,
        )
        onSuccess(`Successfully withdrew ₹${amountRupees} from ${selectedAccount.account_name}.`)
        handleReset()
      } else if (activeModal === 'transfer') {
        // Resolve destination account ID if user entered an account number matching an accessible account
        const matchedDest = accounts.find((a) => a.account_number === destinationAccountId.trim())
        const destId = matchedDest ? matchedDest.id : destinationAccountId.trim()

        await transferFunds(
          {
            source_account_id: selectedAccount.id,
            destination_account_id: destId,
            amount_paise: amountPaise,
            description: description.trim() || 'Peer Transfer via Dashboard',
          },
          idempotencyKey,
        )
        onSuccess(`Successfully transferred ₹${amountRupees} to recipient account.`)
        handleReset()
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Operation failed. Please verify your details and retry.')
      setIsConfirming(false)
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!activeModal) return null

  const modalTitles = {
    deposit: 'Deposit Funds to Account',
    withdraw: 'Withdraw Funds from Account',
    transfer: 'Peer-to-Peer Fund Transfer',
  }

  return (
    <Modal isOpen={Boolean(activeModal)} onClose={handleReset} title={modalTitles[activeModal]}>
      {errorMessage && (
        <Alert type="error" message={errorMessage} onClose={() => setErrorMessage(null)} />
      )}

      {isConfirming ? (
        /* Confirmation Dialog Step */
        <div className="financial-confirmation-dialog">
          <div className="confirm-icon" aria-hidden="true">
            {activeModal === 'deposit' && '📥'}
            {activeModal === 'withdraw' && '📤'}
            {activeModal === 'transfer' && '⇄'}
          </div>
          <h4>Confirm Financial Transaction</h4>
          <p className="text-muted text-sm">
            Please review the details below. This action will post an immutable entry to the double-entry banking ledger.
          </p>

          <div className="confirmation-summary-card">
            <div className="confirm-row">
              <span className="confirm-label">Operation</span>
              <span className="confirm-val font-semibold text-uppercase">{activeModal}</span>
            </div>
            <div className="confirm-row">
              <span className="confirm-label">
                {activeModal === 'transfer' ? 'Source Account' : 'Account'}
              </span>
              <span className="confirm-val">
                {selectedAccount?.account_name} ({selectedAccount?.account_number})
              </span>
            </div>
            {activeModal === 'transfer' && (
              <div className="confirm-row">
                <span className="confirm-label">Destination</span>
                <span className="confirm-val font-mono">{destinationAccountId}</span>
              </div>
            )}
            <div className="confirm-row">
              <span className="confirm-label">Amount</span>
              <span className="confirm-val font-bold text-primary font-mono text-lg">
                ₹{Number(amountRupees).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>
            </div>
            {description && (
              <div className="confirm-row">
                <span className="confirm-label">Note</span>
                <span className="confirm-val">{description}</span>
              </div>
            )}
          </div>

          <div className="modal-actions-footer">
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => setIsConfirming(false)}
              disabled={isSubmitting}
            >
              ← Back to Edit
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleExecuteOperation}
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <span className="spinner-sm" />
                  Posting to Ledger...
                </>
              ) : (
                'Confirm & Execute'
              )}
            </button>
          </div>
        </div>
      ) : (
        /* Form Input Step */
        <form onSubmit={handleInitialSubmit} className="quick-action-form">
          <div className="form-group">
            <label htmlFor="selectAccount">Select Account</label>
            <select
              id="selectAccount"
              className="form-control"
              value={selectedAccountId}
              onChange={(e) => setSelectedAccountId(e.target.value)}
              disabled={isSubmitting}
            >
              {accounts.map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.account_name} ({acc.account_number}) — Balance: ₹
                  {(acc.balance / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </option>
              ))}
            </select>
          </div>

          {activeModal === 'transfer' && (
            <div className="form-group">
              <label htmlFor="destinationAccountId">Recipient Account Identifier or Number</label>
              <input
                id="destinationAccountId"
                type="text"
                className="form-control"
                placeholder="e.g. LL-1234567890 or recipient UUID"
                value={destinationAccountId}
                onChange={(e) => setDestinationAccountId(e.target.value)}
                required
                disabled={isSubmitting}
              />
              <span className="form-hint">Enter the recipient's LedgerLine account number</span>
            </div>
          )}

          <div className="form-group">
            <label htmlFor="amountRupees">Amount (INR)</label>
            <div className="amount-input-group">
              <span className="currency-prefix">₹</span>
              <input
                id="amountRupees"
                type="text"
                className="form-control amount-input"
                placeholder="0.00"
                value={amountRupees}
                onChange={(e) => setAmountRupees(e.target.value)}
                required
                disabled={isSubmitting}
              />
            </div>

            {/* Quick Amount Pills */}
            <div className="quick-amounts-bar">
              <span className="quick-label">Quick select:</span>
              {[500, 1000, 5000, 10000].map((amt) => (
                <button
                  key={amt}
                  type="button"
                  className="quick-amt-pill"
                  onClick={() => handleQuickAmount(amt)}
                >
                  +₹{amt.toLocaleString('en-IN')}
                </button>
              ))}
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="description">Note / Reference (Optional)</label>
            <input
              id="description"
              type="text"
              className="form-control"
              placeholder="e.g. Rent payment, bill clearance, cash addition"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={255}
              disabled={isSubmitting}
            />
          </div>

          <div className="modal-actions-footer">
            <button
              type="button"
              className="btn btn-outline"
              onClick={handleReset}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              Review Transaction →
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
