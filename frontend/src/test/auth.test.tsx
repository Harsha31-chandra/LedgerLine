import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import { LoginPage } from '../pages/LoginPage'
import { RegisterPage } from '../pages/RegisterPage'
import { ProtectedRoute } from '../components/ProtectedRoute'
import * as authApi from '../api/auth'

vi.mock('../api/auth')

describe('Authentication & Session Management', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(authApi.getCurrentUser).mockRejectedValue(new Error('Unauthorized'))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders login page and allows quick demo credential selection', async () => {
    vi.mocked(authApi.getCurrentUser).mockRejectedValueOnce(new Error('Unauthorized'))

    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Sign in to LedgerLine/i })).toBeInTheDocument()
    })

    // Click Admin demo button
    const adminBtn = screen.getByRole('button', { name: /Admin/i })
    fireEvent.click(adminBtn)

    expect(screen.getByLabelText(/Email address/i)).toHaveValue('admin@ledgerline.com')
    expect(screen.getByLabelText(/Password/i)).toHaveValue('SecurePass123!')
  })

  it('submits login form and navigates on success', async () => {
    vi.mocked(authApi.getCurrentUser).mockRejectedValueOnce(new Error('Unauthorized'))
    vi.mocked(authApi.loginUser).mockResolvedValueOnce({
      id: 'user-1',
      email: 'admin@ledgerline.com',
      full_name: 'System Administrator',
      role: 'ADMIN',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })

    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<div>Dashboard Home</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )

    fireEvent.change(screen.getByLabelText(/Email address/i), {
      target: { value: 'admin@ledgerline.com' },
    })
    fireEvent.change(screen.getByLabelText(/Password/i), {
      target: { value: 'SecurePass123!' },
    })

    fireEvent.click(screen.getByRole('button', { name: /^Sign In$/i }))

    await waitFor(() => {
      expect(authApi.loginUser).toHaveBeenCalledWith({
        email: 'admin@ledgerline.com',
        password: 'SecurePass123!',
      })
    })

    await waitFor(() => {
      expect(screen.getByText('Dashboard Home')).toBeInTheDocument()
    })
  })

  it('restores authenticated session automatically on mount', async () => {
    vi.mocked(authApi.getCurrentUser).mockResolvedValueOnce({
      id: 'user-holder',
      email: 'holder@ledgerline.com',
      full_name: 'Customer Holder',
      role: 'HOLDER',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })

    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<div>Protected Dashboard Content</div>} />
            </Route>
            <Route path="/login" element={<div>Login Page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('Protected Dashboard Content')).toBeInTheDocument()
    })
  })

  it('redirects unauthenticated users from protected routes to /login', async () => {
    vi.mocked(authApi.getCurrentUser).mockRejectedValueOnce(new Error('Unauthorized'))

    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<div>Protected Dashboard Content</div>} />
            </Route>
            <Route path="/login" element={<div>Login Required Page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('Login Required Page')).toBeInTheDocument()
    })
  })

  it('validates password mismatch on registration page', async () => {
    render(
      <MemoryRouter initialEntries={['/register']}>
        <AuthProvider>
          <RegisterPage />
        </AuthProvider>
      </MemoryRouter>,
    )

    fireEvent.change(screen.getByLabelText(/Full legal name/i), {
      target: { value: 'Alice Smith' },
    })
    fireEvent.change(screen.getByLabelText(/Email address/i), {
      target: { value: 'alice@example.com' },
    })
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: 'Pass123!' },
    })
    fireEvent.change(screen.getByLabelText(/Confirm password/i), {
      target: { value: 'DifferentPass!' },
    })

    fireEvent.click(screen.getByRole('button', { name: /Complete Registration/i }))

    expect(await screen.findByText('Passwords do not match.')).toBeInTheDocument()
    expect(authApi.registerUser).not.toHaveBeenCalled()
  })
})
