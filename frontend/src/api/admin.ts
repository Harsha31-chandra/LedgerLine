import { apiClient } from './client'
import type {
  Account,
  AdminStats,
  AdminUser,
  AssignMembershipRequest,
  AuditEvent,
  GlobalOverview,
  Transaction,
} from '../types/api'

export async function getAdminStats(): Promise<AdminStats> {
  return apiClient<AdminStats>('/admin/stats', {
    method: 'GET',
  })
}

export async function getAdminUsers(): Promise<AdminUser[]> {
  return apiClient<AdminUser[]>('/admin/users', {
    method: 'GET',
  })
}

export async function assignAccountMembership(
  payload: AssignMembershipRequest,
): Promise<{ message: string; membership_role: string }> {
  return apiClient<{ message: string; membership_role: string }>('/admin/memberships', {
    method: 'POST',
    body: payload,
  })
}

export async function getAdminAuditLogs(
  limit = 50,
  offset = 0,
  action?: string,
): Promise<AuditEvent[]> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('offset', String(offset))
  if (action) params.set('action', action)
  return apiClient<AuditEvent[]>(`/admin/audit-logs?${params.toString()}`, {
    method: 'GET',
  })
}

// Auditor read-only APIs
export async function getGlobalOverview(): Promise<GlobalOverview> {
  return apiClient<GlobalOverview>('/audit/overview', {
    method: 'GET',
  })
}

export async function getAuditAccounts(): Promise<Account[]> {
  return apiClient<Account[]>('/audit/accounts', {
    method: 'GET',
  })
}

export async function getAuditTransactions(limit = 50, offset = 0): Promise<Transaction[]> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('offset', String(offset))
  return apiClient<Transaction[]>(`/audit/transactions?${params.toString()}`, {
    method: 'GET',
  })
}

export async function getAuditLogs(
  limit = 50,
  offset = 0,
  action?: string,
): Promise<AuditEvent[]> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('offset', String(offset))
  if (action) params.set('action', action)
  return apiClient<AuditEvent[]>(`/audit/logs?${params.toString()}`, {
    method: 'GET',
  })
}
