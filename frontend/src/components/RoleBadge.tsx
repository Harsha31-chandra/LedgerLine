import type { MembershipRole, UserRole } from '../types/api'

interface RoleBadgeProps {
  role: UserRole | MembershipRole | string
  type?: 'user' | 'membership'
}

export function RoleBadge({ role, type = 'user' }: RoleBadgeProps) {
  let badgeClass = 'badge-neutral'

  if (type === 'user') {
    switch (role) {
      case 'ADMIN':
        badgeClass = 'badge-admin'
        break
      case 'AUDITOR':
        badgeClass = 'badge-auditor'
        break
      case 'HOLDER':
        badgeClass = 'badge-holder'
        break
    }
  } else {
    switch (role) {
      case 'OWNER':
        badgeClass = 'badge-owner'
        break
      case 'OPERATOR':
        badgeClass = 'badge-operator'
        break
      case 'VIEWER':
        badgeClass = 'badge-viewer'
        break
    }
  }

  return <span className={`badge ${badgeClass}`}>{role}</span>
}
