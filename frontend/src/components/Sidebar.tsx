import type { User } from '../types/api'

export type DashboardTab =
  | 'overview'
  | 'accounts'
  | 'transactions'
  | 'deposit'
  | 'withdraw'
  | 'transfer'
  | 'statements'
  | 'profile'

interface SidebarProps {
  activeTab: DashboardTab
  onSelectTab: (tab: DashboardTab) => void
  user: User | null
  accountsCount: number
}

export function Sidebar({ activeTab, onSelectTab, user, accountsCount }: SidebarProps) {
  const isAuditor = user?.role === 'AUDITOR'

  const navItems: {
    id: DashboardTab
    label: string
    icon: string
    badge?: string | number
    disabled?: boolean
    tooltip?: string
  }[] = [
    {
      id: 'overview',
      label: 'Overview',
      icon: '📊',
    },
    {
      id: 'accounts',
      label: 'My Accounts',
      icon: '💳',
      badge: accountsCount > 0 ? accountsCount : undefined,
    },
    {
      id: 'transactions',
      label: 'Transactions',
      icon: '📜',
    },
    {
      id: 'deposit',
      label: 'Deposit Funds',
      icon: '📥',
      disabled: isAuditor,
      tooltip: isAuditor ? 'Auditor accounts have read-only permissions' : undefined,
    },
    {
      id: 'withdraw',
      label: 'Withdraw Funds',
      icon: '📤',
      disabled: isAuditor,
      tooltip: isAuditor ? 'Auditor accounts have read-only permissions' : undefined,
    },
    {
      id: 'transfer',
      label: 'Transfer Funds',
      icon: '⇄',
      disabled: isAuditor,
      tooltip: isAuditor ? 'Auditor accounts have read-only permissions' : undefined,
    },
    {
      id: 'statements',
      label: 'Statements',
      icon: '📑',
    },
    {
      id: 'profile',
      label: 'Profile & Settings',
      icon: '⚙️',
    },
  ]

  return (
    <aside className="dashboard-sidebar" aria-label="Dashboard Navigation">
      <div className="sidebar-section-title">Navigation</div>
      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const isActive = activeTab === item.id
          return (
            <button
              key={item.id}
              type="button"
              className={`sidebar-nav-item ${isActive ? 'active' : ''} ${
                item.disabled ? 'disabled' : ''
              }`}
              onClick={() => !item.disabled && onSelectTab(item.id)}
              disabled={item.disabled}
              title={item.tooltip}
            >
              <span className="sidebar-item-icon" aria-hidden="true">
                {item.icon}
              </span>
              <span className="sidebar-item-label">{item.label}</span>
              {item.badge !== undefined && (
                <span className="sidebar-item-badge">{item.badge}</span>
              )}
              {item.disabled && <span className="sidebar-read-only-tag">View Only</span>}
            </button>
          )
        })}
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-ledger-status">
          <div className="status-indicator-dot online" />
          <div className="status-text-block">
            <span className="status-title">Core Ledger Live</span>
            <span className="status-meta">PostgreSQL Double-Entry</span>
          </div>
        </div>
      </div>
    </aside>
  )
}
