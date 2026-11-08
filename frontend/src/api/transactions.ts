import { apiClient } from './client'
import type {
  AccountStatement,
  DepositRequest,
  Transaction,
  TransferRequest,
  WithdrawalRequest,
} from '../types/api'

export async function depositFunds(
  payload: DepositRequest,
  idempotencyKey: string,
): Promise<Transaction> {
  return apiClient<Transaction>('/transactions/deposit', {
    method: 'POST',
    body: payload,
    idempotencyKey,
  })
}

export async function withdrawFunds(
  payload: WithdrawalRequest,
  idempotencyKey: string,
): Promise<Transaction> {
  return apiClient<Transaction>('/transactions/withdraw', {
    method: 'POST',
    body: payload,
    idempotencyKey,
  })
}

export async function transferFunds(
  payload: TransferRequest,
  idempotencyKey: string,
): Promise<Transaction> {
  return apiClient<Transaction>('/transactions/transfer', {
    method: 'POST',
    body: payload,
    idempotencyKey,
  })
}

export async function getTransaction(transactionId: string): Promise<Transaction> {
  return apiClient<Transaction>(`/transactions/${transactionId}`, {
    method: 'GET',
  })
}

export async function getAccountStatement(accountId: string): Promise<AccountStatement> {
  return apiClient<AccountStatement>(`/accounts/${accountId}/statement`, {
    method: 'GET',
  })
}
