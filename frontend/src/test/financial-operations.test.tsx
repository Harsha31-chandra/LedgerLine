import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AccountDetailPage } from '../pages/AccountDetailPage'
import { AuthContext } from '../context/authContextDef'
import * as accountsApi from '../api/accounts'
import * as txApi from '../api/transactions'
import type { User, AccountWithMembership, AccountStatement, Transaction } from '../types/api'

vi.mock('../api/accounts')
vi.mock('../api/transactions')

const mockUser: User = {
  id: 'user-holder',
  email: 'holder@ledgerline.com',
  full_name: 'Customer Holder',
  role: 'HOLDER',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const mockAccount: AccountWithMembership = {
  id: 'acc-1111-2222',
  account_number: 'LL-2026-8888',
  account_name: 'Treasury Account',
  currency: 'INR',
  balance: 100000, // ₹1,000.00
  status: 'ACTIVE',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  membership_role: 'OWNER',
}

const mockStatement: AccountStatement = {
  account_id: 'acc-1111-2222',
  account_number: 'LL-2026-8888',
  currency: 'INR',
  balance_paise: 100000,
  entries: [
    {
      id: 'entry-1',
      transaction_id: 'tx-100',
      reference: 'TXN-DEP-100',
      transaction_type: 'DEPOSIT',
      entry_type: 'CREDIT',
      amount_paise: 100000,
      description: 'Initial deposit funding',
      created_at: '2026-01-02T10:00:00Z',
    },
  ],
}

const mockTxDetail: Transaction = {
  id: 'tx-100',
  reference: 'TXN-DEP-100',
  transaction_type: 'DEPOSIT',
  status: 'POSTED',
  amount_paise: 100000,
  currency: 'INR',
  description: 'Initial deposit funding',
  initiated_by: 'user-holder',
  created_at: '2026-01-02T10:00:00Z',
  ledger_entries: [
    {
      id: 'leg-1',
      transaction_id: 'tx-100',
      account_id: 'sys-clearing-id',
      entry_type: 'DEBIT',
      amount_paise: 100000,
      created_at: '2026-01-02T10:00:00Z',
    },
    {
      id: 'leg-2',
      transaction_id: 'tx-100',
      account_id: 'acc-1111-2222',
      entry_type: 'CREDIT',
      amount_paise: 100000,
      created_at: '2026-01-02T10:00:00Z',
    },
  ],
}

describe('Financial Operations & Statement Details', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(accountsApi.getAccount).mockResolvedValue(mockAccount)
    vi.mocked(txApi.getAccountStatement).mockResolvedValue(mockStatement)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  const renderComponent = () => {
    return render(
      <MemoryRouter initialEntries={['/accounts/acc-1111-2222']}>
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
          <Routes>
            <Route path="/accounts/:accountId" element={<AccountDetailPage />} />
          </Routes>
        </AuthContext.Provider>
      </MemoryRouter>,
    )
  }

  it('renders account details and chronological statement table', async () => {
    renderComponent()

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Treasury Account' })).toBeInTheDocument()
      expect(screen.getByText('LL-2026-8888')).toBeInTheDocument()
      expect(screen.getByText('TXN-DEP-100')).toBeInTheDocument()
      expect(screen.getByText('CREDIT')).toBeInTheDocument()
      expect(screen.getByText('Initial deposit funding')).toBeInTheDocument()
    })
  })

  it('opens deposit modal and submits with unique idempotency key', async () => {
    vi.mocked(txApi.depositFunds).mockResolvedValueOnce(mockTxDetail)

    renderComponent()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /\+ Deposit/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /\+ Deposit/i }))

    expect(screen.getByRole('heading', { name: /Deposit into Treasury Account/i })).toBeInTheDocument()

    // Enter amount ₹50.25 -> 5025 paise
    const amountInput = screen.getByLabelText(/Amount \(in INR\)/i)
    fireEvent.change(amountInput, { target: { value: '50.25' } })

    const descInput = screen.getByLabelText(/Description \(optional\)/i)
    fireEvent.change(descInput, { target: { value: 'Test Deposit' } })

    const confirmBtn = screen.getByRole('button', { name: /Confirm Deposit/i })
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(txApi.depositFunds).toHaveBeenCalledWith(
        {
          account_id: 'acc-1111-2222',
          amount_paise: 5025,
          description: 'Test Deposit',
        },
        expect.any(String), // idempotency key
      )
    })
  })

  it('preserves idempotency key on failure so retry reuses the exact same key', async () => {
    let capturedKey = ''
    vi.mocked(txApi.depositFunds).mockImplementationOnce((_payload, key) => {
      capturedKey = key
      return Promise.reject(new Error('Network glitch or transient failure'))
    })

    renderComponent()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /\+ Deposit/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /\+ Deposit/i }))

    fireEvent.change(screen.getByLabelText(/Amount \(in INR\)/i), { target: { value: '25.00' } })
    fireEvent.click(screen.getByRole('button', { name: /Confirm Deposit/i }))

    // First attempt fails
    await waitFor(() => {
      expect(screen.getByText('Network glitch or transient failure')).toBeInTheDocument()
    })

    // Now resolve on retry
    vi.mocked(txApi.depositFunds).mockResolvedValueOnce(mockTxDetail)

    fireEvent.click(screen.getByRole('button', { name: /Confirm Deposit/i }))

    await waitFor(() => {
      expect(txApi.depositFunds).toHaveBeenCalledTimes(2)
      // Second call must use the exact same key!
      const secondCallKey = vi.mocked(txApi.depositFunds).mock.calls[1][1]
      expect(secondCallKey).toBe(capturedKey)
    })
  })

  it('validates withdrawal amount cannot exceed current balance', async () => {
    renderComponent()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /- Withdraw/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /- Withdraw/i }))

    // Balance is ₹1,000.00. Attempt ₹2,000.00
    fireEvent.change(screen.getByLabelText(/Amount \(in INR\)/i), { target: { value: '2000.00' } })
    fireEvent.click(screen.getByRole('button', { name: /Confirm Withdrawal/i }))

    expect(
      await screen.findByText(/Insufficient balance\. Current balance is ₹1,000\.00\./i),
    ).toBeInTheDocument()
    expect(txApi.withdrawFunds).not.toHaveBeenCalled()
  })

  it('validates transfer prevents same source and destination account ID', async () => {
    renderComponent()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /⇄ Transfer/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /⇄ Transfer/i }))

    fireEvent.change(screen.getByLabelText(/Destination Account UUID/i), {
      target: { value: 'acc-1111-2222' },
    })
    fireEvent.change(screen.getByLabelText(/Amount \(in INR\)/i), { target: { value: '50.00' } })
    fireEvent.click(screen.getByRole('button', { name: /Execute Transfer/i }))

    expect(
      await screen.findByText('Source and destination accounts cannot be identical.'),
    ).toBeInTheDocument()
    expect(txApi.transferFunds).not.toHaveBeenCalled()
  })

  it('inspects double-entry ledger entries in audit modal', async () => {
    vi.mocked(txApi.getTransaction).mockResolvedValueOnce(mockTxDetail)

    renderComponent()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Inspect' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Inspect' }))

    await waitFor(() => {
      expect(screen.getByText('Double-Entry Ledger Audit')).toBeInTheDocument()
      expect(screen.getByText('sys-clearing-id')).toBeInTheDocument()
      expect(screen.getByText('acc-1111-2222')).toBeInTheDocument()
      expect(screen.getByText(/Total Debits == Total Credits/i)).toBeInTheDocument()
    })
  })
})
