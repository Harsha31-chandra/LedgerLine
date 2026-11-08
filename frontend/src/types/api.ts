/**
 * LedgerLine API schema types matching backend Pydantic models 1:1.
 */

export type UserRole = 'ADMIN' | 'HOLDER' | 'AUDITOR'

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  created_at: string
  updated_at: string
}

export type AccountStatus = 'ACTIVE' | 'FROZEN' | 'CLOSED'
export type MembershipRole = 'OWNER' | 'SIGNER' | 'VIEWER'

export interface Account {
  id: string
  account_number: string
  account_name: string
  currency: string
  balance: number // in minor units (paise)
  status: AccountStatus
  created_at: string
  updated_at: string
}

export interface AccountWithMembership extends Account {
  membership_role: MembershipRole
}

export type TransactionType = 'DEPOSIT' | 'WITHDRAWAL' | 'TRANSFER'
export type TransactionStatus = 'POSTED' | 'PENDING' | 'FAILED'
export type EntryType = 'DEBIT' | 'CREDIT'

export interface LedgerEntry {
  id: string
  transaction_id: string
  account_id: string
  entry_type: EntryType
  amount_paise: number
  created_at: string
}

export interface Transaction {
  id: string
  reference: string
  transaction_type: TransactionType
  status: TransactionStatus
  amount_paise: number
  currency: string
  description: string | null
  initiated_by: string | null
  created_at: string
  ledger_entries: LedgerEntry[]
}

export interface AccountStatementItem {
  id: string
  transaction_id: string
  reference: string
  transaction_type: TransactionType
  entry_type: EntryType
  amount_paise: number
  description: string | null
  created_at: string
}

export interface AccountStatement {
  account_id: string
  account_number: string
  currency: string
  balance_paise: number
  entries: AccountStatementItem[]
}

// Request Types
export interface UserRegisterRequest {
  email: string
  password: string
  full_name: string
}

export interface UserLoginRequest {
  email: string
  password: string
}

export interface AccountCreateRequest {
  account_name: string
  currency: string
  owner_user_id?: string
}

export interface AccountUpdateRequest {
  account_name: string
}

export interface AccountStatusUpdateRequest {
  status: AccountStatus
}

export interface DepositRequest {
  account_id: string
  amount_paise: number
  description?: string
}

export interface WithdrawalRequest {
  account_id: string
  amount_paise: number
  description?: string
}

export interface TransferRequest {
  source_account_id: string
  destination_account_id: string
  amount_paise: number
  description?: string
}

export interface ApiErrorDetail {
  loc?: (string | number)[]
  msg?: string
  type?: string
}

export interface ApiErrorResponse {
  detail?: string | ApiErrorDetail[]
  message?: string
}
