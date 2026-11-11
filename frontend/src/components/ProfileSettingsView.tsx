import { RoleBadge } from './RoleBadge'
import type { User } from '../types/api'

interface ProfileSettingsViewProps {
  user: User | null
}

export function ProfileSettingsView({ user }: ProfileSettingsViewProps) {
  if (!user) return null

  return (
    <div className="profile-settings-section">
      <div className="profile-header-banner">
        <div className="profile-avatar" aria-hidden="true">
          {user.full_name?.charAt(0).toUpperCase() || 'U'}
        </div>
        <div className="profile-meta-main">
          <h2>{user.full_name}</h2>
          <p className="text-muted text-sm font-mono">{user.email}</p>
          <div className="profile-badges" style={{ marginTop: '0.5rem' }}>
            <RoleBadge role={user.role} type="user" />
            <span className="badge badge-owner">Account Active</span>
          </div>
        </div>
      </div>

      <div className="settings-grid">
        {/* User Identity Card */}
        <div className="settings-card">
          <h3 className="settings-card-title">User Account Identity</h3>
          <div className="settings-kv-list">
            <div className="settings-kv">
              <span className="kv-key">Internal User UUID</span>
              <span className="kv-val font-mono text-xs">{user.id}</span>
            </div>
            <div className="settings-kv">
              <span className="kv-key">Registered Email</span>
              <span className="kv-val">{user.email}</span>
            </div>
            <div className="settings-kv">
              <span className="kv-key">Global System Role</span>
              <span className="kv-val font-semibold">{user.role}</span>
            </div>
            <div className="settings-kv">
              <span className="kv-key">Registration Date</span>
              <span className="kv-val">
                {new Date(user.created_at).toLocaleDateString('en-IN', {
                  year: 'numeric',
                  month: 'long',
                  day: 'numeric',
                })}
              </span>
            </div>
          </div>
        </div>

        {/* Security & Cryptography Controls Card */}
        <div className="settings-card">
          <h3 className="settings-card-title">Security & Ledger Guarantees</h3>
          <div className="settings-kv-list">
            <div className="settings-kv">
              <span className="kv-key">Password Hash</span>
              <span className="kv-val font-mono text-xs">Argon2id (RFC 9106)</span>
            </div>
            <div className="settings-kv">
              <span className="kv-key">Session Cookie</span>
              <span className="kv-val font-mono text-xs">HttpOnly • SameSite=Lax • SHA-256</span>
            </div>
            <div className="settings-kv">
              <span className="kv-key">Double-Entry Verification</span>
              <span className="kv-val text-success font-semibold">Active & Enforced</span>
            </div>
            <div className="settings-kv">
              <span className="kv-key">Ledger Immutability</span>
              <span className="kv-val text-success font-semibold">Database Triggers ON</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
