import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listAccounts } from '../api/accounts'
import { listTransactions } from '../api/transactions'
import { Alert } from '../components/Alert'
import { CurrencyAmount } from '../components/CurrencyAmount'
import { RoleBadge } from '../components/RoleBadge'
import { StatusBadge } from '../components/StatusBadge'
import { Sidebar, type DashboardTab } from '../components/Sidebar'
import { OnboardingWelcome } from '../components/OnboardingWelcome'
import { AccountOpeningModal } from '../components/AccountOpeningModal'
import { RecentTransactionsTable } from '../components/RecentTransactionsTable'
import { QuickActionModals } from '../components/QuickActionModals'
import { StatementsViewer } from '../components/StatementsViewer'
import { ProfileSettingsView } from '../components/ProfileSettingsView'
import { Toast } from '../components/Toast'
import { AuditorDashboardPage } from './AuditorDashboardPage'
import { useAuth } from '../hooks/useAuth'
import type { AccountWithMembership, Transaction } from '../types/api'

export function DashboardPage() {
  const { user } = useAuth()
  const [accounts, setAccounts] = useState<AccountWithMembership[]>([])
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [toastMessage, setToastMessage] = useState<string | null>(null)

  // Navigation tab state
  const [activeTab, setActiveTab] = useState<DashboardTab>('overview')

  // Modals state
  const [isOpeningAccountModalOpen, setIsOpeningAccountModalOpen] = useState(false)
  const [quickActionModal, setQuickActionModal] = useState<'deposit' | 'withdraw' | 'transfer' | null>(null)

  // Load accounts and transactions from backend APIs
  const loadDashboardData = useCallback(async () => {
    setIsLoading(true)
    setErrorMessage(null)
    try {
      const [accs, txs] = await Promise.all([
        listAccounts(),
        listTransactions(100, 0).catch(() => []),
      ])
      setAccounts(accs)
      setTransactions(txs)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load banking ledger data.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let isMounted = true
    Promise.all([
      listAccounts(),
      listTransactions(100, 0).catch(() => []),
    ])
      .then(([accs, txs]) => {
        if (isMounted) {
          setAccounts(accs)
          setTransactions(txs)
        }
      })
      .catch((err: any) => {
        if (isMounted) {
          setErrorMessage(err.message || 'Failed to load banking ledger data.')
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

  // Aggregate financial metrics
  const totalBalancePaise = accounts.reduce((acc, account) => acc + account.balance, 0)
  const userAccountIds = accounts.map((a) => a.id)

  // Calculate deposits and withdrawals from real ledger entries
  const totalDepositsPaise = transactions.reduce((acc, tx) => {
    if (tx.transaction_type === 'DEPOSIT') {
      return acc + tx.amount_paise
    }
    // For transfers: if user received credit
    const userCredit = (tx.ledger_entries || [])
      .filter((e) => userAccountIds.includes(e.account_id) && e.entry_type === 'CREDIT')
      .reduce((sum, e) => sum + e.amount_paise, 0)
    return acc + userCredit
  }, 0)

  const totalWithdrawalsPaise = transactions.reduce((acc, tx) => {
    if (tx.transaction_type === 'WITHDRAWAL') {
      return acc + tx.amount_paise
    }
    // For transfers: if user was debited
    const userDebit = (tx.ledger_entries || [])
      .filter((e) => userAccountIds.includes(e.account_id) && e.entry_type === 'DEBIT')
      .reduce((sum, e) => sum + e.amount_paise, 0)
    return acc + userDebit
  }, 0)

  const handleAccountCreated = (newAccount: AccountWithMembership) => {
    setAccounts((prev) => [newAccount, ...prev])
    setToastMessage(`Account "${newAccount.account_name}" opened successfully!`)
    loadDashboardData()
  }

  const handleQuickActionSuccess = (msg: string) => {
    setToastMessage(msg)
    loadDashboardData()
  }

  const isAuditor = user?.role === 'AUDITOR'

  if (isAuditor) {
    return <AuditorDashboardPage />
  }

  return (
    <div className="dashboard-container">
      {/* Toast Notification */}
      <Toast
        message={toastMessage}
        type="success"
        onClose={() => setToastMessage(null)}
      />

      {/* Account Opening Modal */}
      <AccountOpeningModal
        isOpen={isOpeningAccountModalOpen}
        onClose={() => setIsOpeningAccountModalOpen(false)}
        user={user}
        onAccountCreated={handleAccountCreated}
      />

      {/* Quick Action Modals (Deposit, Withdraw, Transfer) */}
      <QuickActionModals
        activeModal={quickActionModal}
        onClose={() => setQuickActionModal(null)}
        accounts={accounts}
        onSuccess={handleQuickActionSuccess}
      />

      {/* Header Bar */}
      <div className="dashboard-top-bar">
        <div className="top-bar-left">
          <div className="user-greeting-block">
            <h1 className="dashboard-user-title">
              Hello, {user?.full_name?.split(' ')[0] || user?.full_name}
            </h1>
            <p className="dashboard-user-subtitle">
              Manage your accounts and double-entry ledger transactions
            </p>
          </div>
        </div>

        <div className="top-bar-right">
          <RoleBadge role={user?.role || 'HOLDER'} type="user" />
          <button
            type="button"
            className="btn btn-primary btn-sm open-acc-action-btn"
            onClick={() => setIsOpeningAccountModalOpen(true)}
            disabled={isAuditor}
            title={isAuditor ? 'Auditor accounts have read-only access' : undefined}
          >
            + Open New Account
          </button>
          {user?.role === 'ADMIN' && (
            <Link to="/admin/accounts" className="btn btn-outline btn-sm">
              Admin Console ↗
            </Link>
          )}
        </div>
      </div>

      {errorMessage && (
        <Alert
          type="error"
          message={errorMessage}
          onClose={() => setErrorMessage(null)}
        />
      )}

      {/* Loading Screen */}
      {isLoading && accounts.length === 0 ? (
        <div className="loading-state" style={{ minHeight: '350px' }}>
          <div className="spinner" />
          <p>Connecting to secure double-entry ledger...</p>
        </div>
      ) : accounts.length === 0 ? (
        /* STEP 1: Dedicated New User Onboarding Welcome Experience */
        <OnboardingWelcome
          user={user}
          onOpenAccount={() => setIsOpeningAccountModalOpen(true)}
        />
      ) : (
        /* STEP 2: Main Comprehensive Banking Dashboard */
        <div className="dashboard-main-layout">
          {/* Sidebar Navigation */}
          <Sidebar
            activeTab={activeTab}
            onSelectTab={(tab) => {
              if (tab === 'deposit') setQuickActionModal('deposit')
              else if (tab === 'withdraw') setQuickActionModal('withdraw')
              else if (tab === 'transfer') setQuickActionModal('transfer')
              else setActiveTab(tab)
            }}
            user={user}
            accountsCount={accounts.length}
          />

          {/* Main Dashboard Workspace Content */}
          <main className="dashboard-workspace">
            {/* VIEW 1: Overview */}
            {activeTab === 'overview' && (
              <div className="workspace-view overview-view">
                {/* 4 Financial Summary Stat Cards */}
                <div className="financial-summary-grid">
                  <div className="summary-card total-balance-card">
                    <div className="card-top">
                      <span className="summary-title">Total Balance</span>
                      <span className="summary-icon">💰</span>
                    </div>
                    <div className="summary-amount text-primary">
                      <CurrencyAmount amountPaise={totalBalancePaise} />
                    </div>
                    <span className="summary-caption">Across all authorized accounts</span>
                  </div>

                  <div className="summary-card">
                    <div className="card-top">
                      <span className="summary-title">Total Deposits</span>
                      <span className="summary-icon icon-deposit">📥</span>
                    </div>
                    <div className="summary-amount amount-credit">
                      <CurrencyAmount amountPaise={totalDepositsPaise} />
                    </div>
                    <span className="summary-caption">Lifetime credited ledger funds</span>
                  </div>

                  <div className="summary-card">
                    <div className="card-top">
                      <span className="summary-title">Total Withdrawals</span>
                      <span className="summary-icon icon-withdraw">📤</span>
                    </div>
                    <div className="summary-amount amount-debit">
                      <CurrencyAmount amountPaise={totalWithdrawalsPaise} />
                    </div>
                    <span className="summary-caption">Lifetime debited funds</span>
                  </div>

                  <div className="summary-card">
                    <div className="card-top">
                      <span className="summary-title">Total Accounts</span>
                      <span className="summary-icon">💳</span>
                    </div>
                    <div className="summary-amount font-mono">
                      {accounts.length}
                    </div>
                    <span className="summary-caption">Active ledger accounts</span>
                  </div>
                </div>

                {/* Quick Actions Panel */}
                <div className="quick-actions-panel">
                  <h3 className="panel-title">Quick Actions</h3>
                  <div className="quick-actions-grid">
                    <button
                      type="button"
                      className="quick-action-card"
                      onClick={() => setQuickActionModal('deposit')}
                      disabled={isAuditor}
                    >
                      <span className="action-icon">📥</span>
                      <span className="action-title">Deposit</span>
                      <span className="action-desc">Add funds to account</span>
                    </button>

                    <button
                      type="button"
                      className="quick-action-card"
                      onClick={() => setQuickActionModal('withdraw')}
                      disabled={isAuditor}
                    >
                      <span className="action-icon">📤</span>
                      <span className="action-title">Withdraw</span>
                      <span className="action-desc">Payout cash balance</span>
                    </button>

                    <button
                      type="button"
                      className="quick-action-card"
                      onClick={() => setQuickActionModal('transfer')}
                      disabled={isAuditor}
                    >
                      <span className="action-icon">⇄</span>
                      <span className="action-title">Transfer</span>
                      <span className="action-desc">Peer-to-peer transfer</span>
                    </button>

                    <button
                      type="button"
                      className="quick-action-card"
                      onClick={() => setActiveTab('statements')}
                    >
                      <span className="action-icon">📑</span>
                      <span className="action-title">Statements</span>
                      <span className="action-desc">View double-entry journal</span>
                    </button>
                  </div>
                </div>

                {/* Authorized Financial Accounts Section */}
                <div className="accounts-overview-section">
                  <div className="section-header-row">
                    <div>
                      <h3 className="section-heading">My Financial Accounts</h3>
                      <p className="text-muted text-sm">Authorized wallets and operational accounts</p>
                    </div>
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      onClick={() => setActiveTab('accounts')}
                    >
                      View All ({accounts.length}) →
                    </button>
                  </div>

                  <div className="accounts-grid">
                    {accounts.map((account) => (
                      <div key={account.id} className="premium-account-card">
                        <div className="card-header-line">
                          <div>
                            <h4 className="card-acc-name">{account.account_name}</h4>
                            <span className="card-acc-number font-mono">{account.account_number}</span>
                          </div>
                          <div className="card-badges">
                            <StatusBadge status={account.status} />
                            <RoleBadge role={account.membership_role} type="membership" />
                          </div>
                        </div>

                        <div className="card-balance-section">
                          <span className="card-balance-lbl">Available Balance</span>
                          <div className="card-balance-val text-primary">
                            <CurrencyAmount
                              amountPaise={account.balance}
                              currency={account.currency}
                            />
                          </div>
                        </div>

                        <div className="card-footer-actions">
                          <span className="currency-pill">{account.currency}</span>
                          <Link
                            to={`/accounts/${account.id}`}
                            className="btn btn-primary btn-sm view-acc-btn"
                          >
                            View Account Details →
                          </Link>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Recent Transactions Section */}
                <div className="recent-transactions-section">
                  <div className="section-header-row">
                    <div>
                      <h3 className="section-heading">Recent Transactions</h3>
                      <p className="text-muted text-sm">Authoritative double-entry ledger postings</p>
                    </div>
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      onClick={() => setActiveTab('transactions')}
                    >
                      View Full Ledger →
                    </button>
                  </div>

                  <RecentTransactionsTable
                    transactions={transactions}
                    isLoading={isLoading}
                    errorMessage={errorMessage}
                    onRefresh={loadDashboardData}
                    userAccountIds={userAccountIds}
                  />
                </div>
              </div>
            )}

            {/* VIEW 2: My Accounts */}
            {activeTab === 'accounts' && (
              <div className="workspace-view accounts-view">
                <div className="section-header-row">
                  <div>
                    <h2 className="section-heading">Financial Accounts Portfolio</h2>
                    <p className="text-muted text-sm">
                      All double-entry accounts where you hold authorized membership
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => setIsOpeningAccountModalOpen(true)}
                    disabled={isAuditor}
                  >
                    + Open Another Account
                  </button>
                </div>

                <div className="accounts-grid" style={{ marginTop: '1.25rem' }}>
                  {accounts.map((account) => (
                    <div key={account.id} className="premium-account-card">
                      <div className="card-header-line">
                        <div>
                          <h4 className="card-acc-name">{account.account_name}</h4>
                          <span className="card-acc-number font-mono">{account.account_number}</span>
                        </div>
                        <div className="card-badges">
                          <StatusBadge status={account.status} />
                          <RoleBadge role={account.membership_role} type="membership" />
                        </div>
                      </div>

                      <div className="card-balance-section">
                        <span className="card-balance-lbl">Available Balance</span>
                        <div className="card-balance-val text-primary">
                          <CurrencyAmount
                            amountPaise={account.balance}
                            currency={account.currency}
                          />
                        </div>
                      </div>

                      <div className="card-footer-actions">
                        <span className="currency-pill">{account.currency}</span>
                        <Link
                          to={`/accounts/${account.id}`}
                          className="btn btn-primary btn-sm view-acc-btn"
                        >
                          View Account Details →
                        </Link>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* VIEW 3: Full Transactions Ledger */}
            {activeTab === 'transactions' && (
              <div className="workspace-view transactions-view">
                <div className="section-header-row">
                  <div>
                    <h2 className="section-heading">Transaction Journal</h2>
                    <p className="text-muted text-sm">
                      Complete searchable audit trail of double-entry financial postings
                    </p>
                  </div>
                </div>

                <RecentTransactionsTable
                  transactions={transactions}
                  isLoading={isLoading}
                  errorMessage={errorMessage}
                  onRefresh={loadDashboardData}
                  userAccountIds={userAccountIds}
                />
              </div>
            )}

            {/* VIEW 4: Statements */}
            {activeTab === 'statements' && (
              <div className="workspace-view statements-view">
                <StatementsViewer accounts={accounts} />
              </div>
            )}

            {/* VIEW 5: Profile & Settings */}
            {activeTab === 'profile' && (
              <div className="workspace-view profile-view">
                <ProfileSettingsView user={user} />
              </div>
            )}
          </main>
        </div>
      )}
    </div>
  )
}
