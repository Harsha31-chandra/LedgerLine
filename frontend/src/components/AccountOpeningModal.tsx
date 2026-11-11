import { useState, type FormEvent } from 'react'
import { Modal } from './Modal'
import { Alert } from './Alert'
import { CurrencyAmount } from './CurrencyAmount'
import { onboardAccount } from '../api/accounts'
import type { AccountType, AccountWithMembership, User } from '../types/api'

interface AccountOpeningModalProps {
  isOpen: boolean
  onClose: () => void
  user: User | null
  onAccountCreated: (account: AccountWithMembership) => void
}

export function AccountOpeningModal({
  isOpen,
  onClose,
  user,
  onAccountCreated,
}: AccountOpeningModalProps) {
  const [accountType, setAccountType] = useState<AccountType>('Savings Account')
  const [accountName, setAccountName] = useState('Primary Savings Account')
  const [includeDemoDeposit, setIncludeDemoDeposit] = useState(true)
  const [hasConfirmedTerms, setHasConfirmedTerms] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [createdAccount, setCreatedAccount] = useState<AccountWithMembership | null>(null)

  const DEMO_DEPOSIT_PAISE = 1_000_000 // ₹10,000 in minor units (paise)

  const handleAccountTypeChange = (newType: AccountType) => {
    setAccountType(newType)
    if (newType === 'Savings Account' && accountName.includes('Current')) {
      setAccountName('Primary Savings Account')
    } else if (newType === 'Current Account' && accountName.includes('Savings')) {
      setAccountName('Primary Current Account')
    }
  }

  const handleResetAndClose = () => {
    setCreatedAccount(null)
    setErrorMessage(null)
    setHasConfirmedTerms(false)
    setIsSubmitting(false)
    onClose()
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setErrorMessage(null)

    if (!accountName.trim()) {
      setErrorMessage('Account name is required.')
      return
    }

    if (includeDemoDeposit && !hasConfirmedTerms) {
      setErrorMessage('Please confirm acknowledgment of the sample demo deposit before proceeding.')
      return
    }

    setIsSubmitting(true)
    try {
      const depositPaise = includeDemoDeposit ? DEMO_DEPOSIT_PAISE : 0
      const account = await onboardAccount({
        account_name: accountName.trim(),
        currency: 'INR',
        account_type: accountType,
        initial_deposit_paise: depositPaise,
      })
      setCreatedAccount(account)
    } catch (err: any) {
      setErrorMessage(
        err.message || 'Failed to open account. Please verify your details or try again.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleProceedToDashboard = () => {
    if (createdAccount) {
      onAccountCreated(createdAccount)
      handleResetAndClose()
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleResetAndClose}
      title={createdAccount ? 'Account Successfully Opened' : 'Open a New Financial Account'}
    >
      {createdAccount ? (
        /* Step 4: Successful Account Creation View */
        <div className="account-creation-success">
          <div className="success-icon-badge" aria-hidden="true">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="22" fill="#DCFCE7" stroke="#16A34A" strokeWidth="2" />
              <path
                d="M14 24L21 31L34 18"
                stroke="#16A34A"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>

          <h3 className="success-heading">Your Account is Ready!</h3>
          <p className="success-subheading">
            Congratulations, <strong>{user?.full_name}</strong>. Your account has been opened and
            registered in the LedgerLine core banking ledger.
          </p>

          {/* Account Card Preview with Confirmed Opening Balance */}
          <div className="preview-card-container active-account-card">
            <div className="preview-card-header">
              <div className="preview-brand">
                <span className="logo-symbol">⚖</span>
                <span className="brand-text">LedgerLine Bank</span>
              </div>
              <span className="account-type-badge">{accountType}</span>
            </div>

            <div className="preview-card-chip" aria-hidden="true">
              <div className="chip-metal" />
            </div>

            <div className="preview-card-number">
              <span>{createdAccount.account_number}</span>
            </div>

            <div className="preview-card-footer">
              <div>
                <span className="preview-meta-label">Account Holder</span>
                <span className="preview-meta-val">{user?.full_name}</span>
              </div>
              <div className="preview-balance-block">
                <span className="preview-meta-label">Confirmed Balance</span>
                <span className="preview-balance-val">
                  <CurrencyAmount
                    amountPaise={createdAccount.balance}
                    currency={createdAccount.currency}
                  />
                </span>
              </div>
            </div>
          </div>

          {createdAccount.balance > 0 && (
            <div className="demo-confirmation-pill">
              <span className="pill-dot" />
              <span>₹10,000.00 Demo Opening Balance credited from System Clearing Reserve</span>
            </div>
          )}

          <div className="modal-actions-right" style={{ marginTop: '1.5rem' }}>
            <button
              type="button"
              className="btn btn-primary btn-lg"
              onClick={handleProceedToDashboard}
            >
              Go to Dashboard →
            </button>
          </div>
        </div>
      ) : (
        /* Step 2 & 3: Account Creation Form & Live Preview */
        <div className="account-opening-layout">
          {errorMessage && (
            <Alert
              type="error"
              message={errorMessage}
              onClose={() => setErrorMessage(null)}
            />
          )}

          {/* Live Interactive Account Card Preview */}
          <div className="account-card-preview-section">
            <span className="preview-section-title">Live Account Card Preview</span>
            <div className="preview-card-container">
              <div className="preview-card-header">
                <div className="preview-brand">
                  <span className="logo-symbol">⚖</span>
                  <span className="brand-text">LedgerLine Bank</span>
                </div>
                <span className="account-type-badge">{accountType}</span>
              </div>

              <div className="preview-card-chip" aria-hidden="true">
                <div className="chip-metal" />
              </div>

              <div className="preview-card-number">
                <span>LL-•••• •••• ••42</span>
              </div>

              <div className="preview-card-footer">
                <div>
                  <span className="preview-meta-label">Account Holder</span>
                  <span className="preview-meta-val">{user?.full_name || 'Account Holder'}</span>
                </div>
                <div className="preview-balance-block">
                  <span className="preview-meta-label">Opening Amount</span>
                  <span className="preview-balance-val">
                    {includeDemoDeposit ? '₹10,000.00' : '₹0.00'}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="account-opening-form">
            <div className="form-group">
              <label htmlFor="holderName">Account Holder Name</label>
              <input
                id="holderName"
                type="text"
                className="form-control"
                value={user?.full_name || ''}
                readOnly
                disabled
              />
              <span className="form-hint">Pre-filled from verified user profile</span>
            </div>

            <div className="form-row">
              <div className="form-group flex-1">
                <label htmlFor="accountType">Account Type</label>
                <select
                  id="accountType"
                  className="form-control"
                  value={accountType}
                  onChange={(e) => handleAccountTypeChange(e.target.value as AccountType)}
                  disabled={isSubmitting}
                >
                  <option value="Savings Account">Savings Account (Standard)</option>
                  <option value="Current Account">Current Account (Operational)</option>
                </select>
              </div>

              <div className="form-group flex-1">
                <label htmlFor="currency">Currency</label>
                <input
                  id="currency"
                  type="text"
                  className="form-control"
                  value="INR (Indian Rupee)"
                  readOnly
                  disabled
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="accountName">Account Name / Nickname</label>
              <input
                id="accountName"
                type="text"
                className="form-control"
                placeholder="e.g. Primary Savings Account"
                value={accountName}
                onChange={(e) => setAccountName(e.target.value)}
                required
                maxLength={100}
                disabled={isSubmitting}
              />
            </div>

            {/* Step 3: Demo Opening Balance Selector */}
            <div className="demo-balance-card">
              <div className="demo-balance-header">
                <label className="demo-checkbox-label">
                  <input
                    type="checkbox"
                    checked={includeDemoDeposit}
                    onChange={(e) => setIncludeDemoDeposit(e.target.checked)}
                    disabled={isSubmitting}
                  />
                  <span className="demo-checkbox-title">
                    Optional Demo Opening Deposit (₹10,000)
                  </span>
                </label>
                <span className="demo-badge">Evaluation Feature</span>
              </div>

              <p className="demo-note">
                <strong>Demo Funds:</strong> This is sample money for local demonstration purposes
                and is not real money. It will be credited via a balanced double-entry transaction
                from the Central System Clearing Reserve.
              </p>

              {includeDemoDeposit && (
                <div className="demo-confirmation-check">
                  <label className="demo-confirm-label">
                    <input
                      type="checkbox"
                      checked={hasConfirmedTerms}
                      onChange={(e) => setHasConfirmedTerms(e.target.checked)}
                      disabled={isSubmitting}
                    />
                    <span>I confirm and authorize crediting ₹10,000 demo funds to this account.</span>
                  </label>
                </div>
              )}
            </div>

            <div className="modal-actions-footer">
              <button
                type="button"
                className="btn btn-outline"
                onClick={handleResetAndClose}
                disabled={isSubmitting}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={isSubmitting || (includeDemoDeposit && !hasConfirmedTerms)}
              >
                {isSubmitting ? (
                  <>
                    <span className="spinner-sm" />
                    Opening Account...
                  </>
                ) : (
                  'Confirm & Open Account'
                )}
              </button>
            </div>
          </form>
        </div>
      )}
    </Modal>
  )
}
