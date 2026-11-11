import { useState } from 'react'
import { Modal } from './Modal'
import type { User } from '../types/api'

interface OnboardingWelcomeProps {
  user: User | null
  onOpenAccount: () => void
}

export function OnboardingWelcome({ user, onOpenAccount }: OnboardingWelcomeProps) {
  const [isDemoInfoOpen, setIsDemoInfoOpen] = useState(false)
  const firstName = user?.full_name?.trim().split(/\s+/)[0] || 'Member'

  return (
    <div className="onboarding-welcome-container">
      <div className="onboarding-hero-card">
        {/* Visual Banking Vault / Ledger SVG Illustration */}
        <div className="onboarding-illustration" aria-hidden="true">
          <svg
            width="140"
            height="140"
            viewBox="0 0 140 140"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <circle cx="70" cy="70" r="66" fill="#EFF6FF" stroke="#BFDBFE" strokeWidth="2" />
            {/* Vault Body */}
            <rect x="36" y="38" width="68" height="64" rx="8" fill="#1E3A8A" />
            <rect x="42" y="44" width="56" height="52" rx="4" fill="#2563EB" />
            {/* Vault Dial */}
            <circle cx="70" cy="70" r="16" fill="#1E3A8A" stroke="#93C5FD" strokeWidth="3" />
            <circle cx="70" cy="70" r="6" fill="#F8FAFC" />
            <line x1="70" y1="56" x2="70" y2="60" stroke="#93C5FD" strokeWidth="2" strokeLinecap="round" />
            <line x1="70" y1="80" x2="70" y2="84" stroke="#93C5FD" strokeWidth="2" strokeLinecap="round" />
            <line x1="56" y1="70" x2="60" y2="70" stroke="#93C5FD" strokeWidth="2" strokeLinecap="round" />
            <line x1="80" y1="70" x2="84" y2="70" stroke="#93C5FD" strokeWidth="2" strokeLinecap="round" />
            {/* Balance Badge / Coin */}
            <circle cx="102" cy="40" r="14" fill="#16A34A" stroke="#FFFFFF" strokeWidth="2" />
            <text x="102" y="45" textAnchor="middle" fill="#FFFFFF" fontSize="12" fontWeight="bold">₹</text>
          </svg>
        </div>

        <div className="onboarding-content">
          <span className="onboarding-badge">New Account Holder</span>
          <h1 className="onboarding-title">Welcome to LedgerLine, {firstName}!</h1>
          <p className="onboarding-subtitle">Your financial journey starts here.</p>

          <p className="onboarding-description">
            LedgerLine is a modern, high-integrity banking ledger platform. You can now open a personal
            financial account, receive optional demo funding for evaluation, and execute balanced double-entry
            deposits, withdrawals, and peer-to-peer transfers with real-time auditability.
          </p>

          {/* Feature Highlights Grid */}
          <div className="onboarding-features-grid">
            <div className="onboarding-feature-item">
              <div className="feature-icon">⚖️</div>
              <div className="feature-text">
                <strong>Double-Entry Accounting</strong>
                <p>Every transaction strictly balances debits and credits across customer wallets.</p>
              </div>
            </div>

            <div className="onboarding-feature-item">
              <div className="feature-icon">⚡</div>
              <div className="feature-text">
                <strong>Instant Financial Actions</strong>
                <p>Deposit, withdraw, or transfer funds seamlessly with optimistic locking and idempotency.</p>
              </div>
            </div>

            <div className="onboarding-feature-item">
              <div className="feature-icon">🛡️</div>
              <div className="feature-text">
                <strong>Tamper-Evident Ledger</strong>
                <p>Chronological statement generation with immutable postings and full audit trails.</p>
              </div>
            </div>
          </div>

          {/* Action CTAs */}
          <div className="onboarding-actions">
            <button
              type="button"
              className="btn btn-primary btn-lg open-account-btn"
              onClick={onOpenAccount}
            >
              <span className="btn-icon">💳</span>
              Open Your First Account
            </button>

            <button
              type="button"
              className="btn btn-outline btn-lg"
              onClick={() => setIsDemoInfoOpen(true)}
            >
              Explore Demo Features
            </button>
          </div>
        </div>
      </div>

      {/* Demo Features Explanatory Modal */}
      <Modal
        isOpen={isDemoInfoOpen}
        onClose={() => setIsDemoInfoOpen(false)}
        title="LedgerLine Demo & Evaluation Guide"
      >
        <div className="demo-guide-content">
          <div className="alert alert-info" style={{ marginBottom: '1.25rem' }}>
            <span className="alert-message">
              <strong>Local Demonstration Environment:</strong> Sample funds and accounts are strictly
              for functional demonstration and testing. No real currency is involved.
            </span>
          </div>

          <h4 style={{ marginBottom: '0.5rem', color: '#1E3A8A' }}>How Demo Funding Works:</h4>
          <ul style={{ paddingLeft: '1.25rem', marginBottom: '1.25rem', lineHeight: '1.6' }}>
            <li>
              <strong>Double-Entry Realism:</strong> When you open your first account with the sample
              ₹10,000 demo credit, the backend automatically debits the Central System Clearing Reserve
              and credits your customer account.
            </li>
            <li>
              <strong>Anti-Duplication:</strong> Demo funds can only be claimed once per user, preventing
              unlimited balance inflation.
            </li>
            <li>
              <strong>Full Banking Capabilities:</strong> Use your initial balance to test peer-to-peer
              transfers, cash withdrawals, and chronological statement exports.
            </li>
          </ul>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => setIsDemoInfoOpen(false)}
            >
              Close
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setIsDemoInfoOpen(false)
                onOpenAccount()
              }}
            >
              Proceed to Open Account →
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
