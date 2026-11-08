import { useEffect, useState, type ReactNode } from 'react'
import { getCurrentUser, loginUser, logoutUser, registerUser } from '../api/auth'
import type { User, UserLoginRequest, UserRegisterRequest } from '../types/api'
import { AuthContext } from './authContextDef'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)

  const refreshUser = async (): Promise<User | null> => {
    try {
      const currentUser = await getCurrentUser()
      setUser(currentUser)
      return currentUser
    } catch {
      setUser(null)
      return null
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    let isMounted = true
    Promise.resolve(getCurrentUser())
      .then((currentUser) => {
        if (isMounted) {
          setUser(currentUser)
        }
      })
      .catch(() => {
        if (isMounted) {
          setUser(null)
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

  const login = async (credentials: UserLoginRequest): Promise<User> => {
    const loggedInUser = await loginUser(credentials)
    setUser(loggedInUser)
    return loggedInUser
  }

  const register = async (payload: UserRegisterRequest): Promise<User> => {
    return registerUser(payload)
  }

  const logout = async (): Promise<void> => {
    try {
      await logoutUser()
    } finally {
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
