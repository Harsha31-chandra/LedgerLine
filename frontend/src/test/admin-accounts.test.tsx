import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AdminAccountsPage } from '../pages/AdminAccountsPage'
import { AuthContext } from '../context/authContextDef'
import * as accountsApi from '../api/accounts'
import type { User, AccountWithMembership } from '../types/api'

vi.mock('../api/accounts')

const adminUser: User = {
  id: 'user-admin',
  email: 'admin@ledgerline.com',
  full_name: 'Administrator',
  role: 'ADMIN',
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

const mockAccounts: AccountWithMembership[] = [
  {
    id: 'acc-1',
    account_number: 'LL-2026-0001',
    account_name: 'Main Customer Account',
    currency: 'INR',
    balance: 50000,
    status: 'ACTIVE',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    membership_role: 'OWNER',
  },
]

describe('Admin Accounts Console', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(accountsApi.listAccounts).mockResolvedValue(mockAccounts)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('blocks non-admin users from viewing admin console', async () => {
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
          <AdminAccountsPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    expect(
      screen.getByText(/Administrator privileges are required to view this console/i),
    ).toBeInTheDocument()
    expect(accountsApi.listAccounts).not.toHaveBeenCalled()
  })

  it('allows admin users to view accounts and create a new account', async () => {
    vi.mocked(accountsApi.createAccount).mockResolvedValueOnce({
      id: 'acc-2',
      account_number: 'LL-2026-0002',
      account_name: 'New Corporate Account',
      currency: 'INR',
      balance: 0,
      status: 'ACTIVE',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      membership_role: 'OWNER',
    })

    render(
      <MemoryRouter>
        <AuthContext.Provider
          value={{
            user: adminUser,
            isLoading: false,
            login: vi.fn(),
            register: vi.fn(),
            logout: vi.fn(),
            refreshUser: vi.fn(),
          }}
        >
          <AdminAccountsPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('Administrative Account Console')).toBeInTheDocument()
      expect(screen.getByText('Main Customer Account')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /\+ Create New Account/i }))

    expect(screen.getByRole('heading', { name: 'Create Financial Account' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Account Name/i), {
      target: { value: 'New Corporate Account' },
    })

    fireEvent.click(screen.getByRole('button', { name: /^Create Account$/i }))

    await waitFor(() => {
      expect(accountsApi.createAccount).toHaveBeenCalledWith({
        account_name: 'New Corporate Account',
        currency: 'INR',
        owner_user_id: undefined,
      })
    })
  })
})
