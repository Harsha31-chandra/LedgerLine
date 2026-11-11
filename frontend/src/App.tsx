import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Navbar } from './components/Navbar'
import { ProtectedRoute } from './components/ProtectedRoute'
import { AuthProvider } from './context/AuthContext'
import { AccountDetailPage } from './pages/AccountDetailPage'
import { AdminAccountsPage } from './pages/AdminAccountsPage'
import { AuditorDashboardPage } from './pages/AuditorDashboardPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { RegisterPage } from './pages/RegisterPage'
import './App.css'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <div className="app-layout">
          <Navbar />
          <main className="main-content">
            <Routes>
              {/* Public Routes */}
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />

              {/* Protected Routes */}
              <Route element={<ProtectedRoute />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/accounts/:accountId" element={<AccountDetailPage />} />
                <Route path="/admin" element={<AdminAccountsPage />} />
                <Route path="/admin/accounts" element={<AdminAccountsPage />} />
                <Route path="/audit" element={<AuditorDashboardPage />} />
              </Route>

              {/* 404 Route */}
              <Route path="/404" element={<NotFoundPage />} />
              <Route path="*" element={<Navigate to="/404" replace />} />
            </Routes>
          </main>
          <footer className="app-footer">
            <div className="footer-container">
              <p className="text-muted text-xs">
                LedgerLine Financial Transaction & Balanced Double-Entry System • Cryptographically Auditable
              </p>
            </div>
          </footer>
        </div>
      </AuthProvider>
    </BrowserRouter>
  )
}
