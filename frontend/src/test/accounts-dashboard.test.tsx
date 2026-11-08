import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { DashboardPage } from '../pages/DashboardPage'
import { AuthContext } from '../context/authContextDef'
import * as accountsApi from '../api/accounts'
import type { User, AccountWithMembership } from '../types/api'

vi.mock('../api/accounts')

const mockUser: User = {
  id: 'user-holder',
  email: 'holder@ledgerline.com',
  full_name: 'Customer Holder',
  role: 'HOLDER',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const mockAccounts: AccountWithMembership[] = [
  {
    id: 'acc-1',
    account_number: 'LL-2026-1001',
    account_name: 'Checking Account',
    currency: 'INR',
    balance: 250000, // ₹2,500.00
    status: 'ACTIVE',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    membership_role: 'OWNER',
  },
  {
    id: 'acc-2',
    account_number: 'LL-2026-1002',
    account_name: 'Savings Reserve',
    currency: 'INR',
    balance: 500000, // ₹5,000.00
    status: 'ACTIVE',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    membership_role: 'SIGNER',
  },
]

describe('Dashboard & Account Listing', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders dashboard with accounts and aggregated portfolio balance', async () => {
    vi.mocked(accountsApi.listAccounts).mockResolvedValueOnce(mockAccounts)

    render(
      <MemoryRouter>
        <AuthContext.Provider
          value={{
            user: mockUser,
            isLoading: false,
            login: vi.fn(),
            register: vi.fn(),
            logout: vi.fn(),
            refreshUser: vi.fn(),
          }}
        >
          <DashboardPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('Checking Account')).toBeInTheDocument()
      expect(screen.getByText('Savings Reserve')).toBeInTheDocument()
      expect(screen.getByText('LL-2026-1001')).toBeInTheDocument()
      expect(screen.getByText('LL-2026-1002')).toBeInTheDocument()
    })

    // Total balance: ₹2,500.00 + ₹5,000.00 = ₹7,500.00
    expect(screen.getByText(/7,500.00/)).toBeInTheDocument()
    expect(screen.getByText('OWNER')).toBeInTheDocument()
    expect(screen.getByText('SIGNER')).toBeInTheDocument()
  })

  it('renders clean empty state when no accounts exist', async () => {
    vi.mocked(accountsApi.listAccounts).mockResolvedValueOnce([])

    render(
      <MemoryRouter>
        <AuthContext.Provider
          value={{
            user: mockUser,
            isLoading: false,
            login: vi.fn(),
            register: vi.fn(),
            logout: vi.fn(),
            refreshUser: vi.fn(),
          }}
        >
          <DashboardPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('No Accounts Found')).toBeInTheDocument()
    })
  })

  it('displays error banner if fetching accounts fails', async () => {
    vi.mocked(accountsApi.listAccounts).mockRejectedValueOnce(
      new Error('Failed to reach ledger database.'),
    )

    render(
      <MemoryRouter>
        <AuthContext.Provider
          value={{
            user: mockUser,
            isLoading: false,
            login: vi.fn(),
            register: vi.fn(),
            logout: vi.fn(),
            refreshUser: vi.fn(),
          }}
        >
          <DashboardPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('Failed to reach ledger database.')).toBeInTheDocument()
    })
  })
})
