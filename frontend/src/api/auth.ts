import { apiClient } from './client'
import type { User, UserLoginRequest, UserRegisterRequest } from '../types/api'

export async function registerUser(payload: UserRegisterRequest): Promise<User> {
  return apiClient<User>('/auth/register', {
    method: 'POST',
    body: payload,
  })
}

export async function loginUser(payload: UserLoginRequest): Promise<User> {
  return apiClient<User>('/auth/login', {
    method: 'POST',
    body: payload,
  })
}

export async function logoutUser(): Promise<{ detail: string }> {
  return apiClient<{ detail: string }>('/auth/logout', {
    method: 'POST',
  })
}

export async function getCurrentUser(): Promise<User> {
  return apiClient<User>('/auth/me', {
    method: 'GET',
  })
}
