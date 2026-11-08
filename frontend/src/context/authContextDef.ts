import { createContext } from 'react'
import type { User, UserLoginRequest, UserRegisterRequest } from '../types/api'

export interface AuthContextType {
  user: User | null
  isLoading: boolean
  login: (credentials: UserLoginRequest) => Promise<User>
  register: (payload: UserRegisterRequest) => Promise<User>
  logout: () => Promise<void>
  refreshUser: () => Promise<User | null>
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined)
