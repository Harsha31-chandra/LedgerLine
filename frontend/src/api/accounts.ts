import { apiClient } from './client'
import type {
  Account,
  AccountCreateRequest,
  AccountOnboardingRequest,
  AccountStatusUpdateRequest,
  AccountUpdateRequest,
  AccountWithMembership,
} from '../types/api'

export async function listAccounts(): Promise<AccountWithMembership[]> {
  return apiClient<AccountWithMembership[]>('/accounts', {
    method: 'GET',
  })
}

export async function getAdminAccounts(): Promise<Account[]> {
  return apiClient<Account[]>('/admin/accounts', {
    method: 'GET',
  })
}

export async function getAccount(accountId: string): Promise<AccountWithMembership> {
  return apiClient<AccountWithMembership>(`/accounts/${accountId}`, {
    method: 'GET',
  })
}

export async function createAccount(payload: AccountCreateRequest): Promise<AccountWithMembership> {
  return apiClient<AccountWithMembership>('/accounts', {
    method: 'POST',
    body: payload,
  })
}

export async function onboardAccount(
  payload: AccountOnboardingRequest,
): Promise<AccountWithMembership> {
  return apiClient<AccountWithMembership>('/accounts/onboarding', {
    method: 'POST',
    body: payload,
  })
}

export async function updateAccount(
  accountId: string,
  payload: AccountUpdateRequest,
): Promise<Account> {
  return apiClient<Account>(`/accounts/${accountId}`, {
    method: 'PATCH',
    body: payload,
  })
}

export async function updateAccountStatus(
  accountId: string,
  payload: AccountStatusUpdateRequest,
): Promise<Account> {
  return apiClient<Account>(`/accounts/${accountId}/status`, {
    method: 'POST',
    body: payload,
  })
}
