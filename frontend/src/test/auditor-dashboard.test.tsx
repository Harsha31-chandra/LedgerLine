import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuditorDashboardPage } from '../pages/AuditorDashboardPage'
import { AuthContext } from '../context/authContextDef'
import * as adminApi from '../api/admin'
import type { User, Account, GlobalOverview } from '../types/api'

vi.mock('../api/admin')

const auditorUser: User = {
  id: 'user-auditor',
  email: 'auditor@ledgerline.com',
  full_name: 'Auditor Oversight',
  role: 'AUDITOR',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const holderUser: User = {
  id: 'user-holder',
  email: 'holder@ledgerline.com',
  full_name: 'Holder User',
  role: 'HOLDER',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const mockOverview: GlobalOverview = {
  total_accounts: 5,
  active_accounts: 4,
  frozen_accounts: 1,
  closed_accounts: 0,
  total_portfolio_balance_paise: 1500000,
  total_transactions: 12,
  total_ledger_entries: 24,
}

const mockAccounts: Account[] = [
  {
    id: 'acc-audit-1',
    account_number: 'LL-2026-9001',
    account_name: 'Audit Target Account',
    currency: 'INR',
    balance: 500000,
    status: 'ACTIVE',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

describe('Auditor Oversight Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(adminApi.getGlobalOverview).mockResolvedValue(mockOverview)
    vi.mocked(adminApi.getAuditAccounts).mockResolvedValue(mockAccounts)
    vi.mocked(adminApi.getAuditTransactions).mockResolvedValue([])
    vi.mocked(adminApi.getAuditLogs).mockResolvedValue([])
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('blocks HOLDER users from viewing auditor oversight console', async () => {
    render(
      <MemoryRouter>
        <AuthContext.Provider
          value={{
            user: holderUser,
            isLoading: false,
            login: vi.fn(),
            register: vi.fn(),
            logout: vi.fn(),
            refreshUser: vi.fn(),
          }}
        >
          <AuditorDashboardPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    expect(
      screen.getByText(/Auditor or Administrator privileges are required to view this oversight console/i),
    ).toBeInTheDocument()
    expect(adminApi.getGlobalOverview).not.toHaveBeenCalled()
  })

  it('allows AUDITOR users to inspect global financial metrics and account inventory', async () => {
    render(
      <MemoryRouter>
        <AuthContext.Provider
          value={{
            user: auditorUser,
            isLoading: false,
            login: vi.fn(),
            register: vi.fn(),
            logout: vi.fn(),
            refreshUser: vi.fn(),
          }}
        >
          <AuditorDashboardPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('Auditor Oversight & Ledger Verification')).toBeInTheDocument()
      expect(screen.getByText('STRICTLY READ-ONLY')).toBeInTheDocument()
      expect(screen.getByText('Audit Target Account')).toBeInTheDocument()
    })
  })
})
