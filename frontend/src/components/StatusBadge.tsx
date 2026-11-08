import type { AccountStatus, TransactionStatus } from '../types/api'

interface StatusBadgeProps {
  status: AccountStatus | TransactionStatus | string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  let badgeClass = 'badge-default'

  switch (status) {
    case 'ACTIVE':
    case 'POSTED':
      badgeClass = 'badge-success'
      break
    case 'FROZEN':
    case 'PENDING':
      badgeClass = 'badge-warning'
      break
    case 'CLOSED':
    case 'FAILED':
      badgeClass = 'badge-danger'
      break
    default:
      badgeClass = 'badge-neutral'
  }

  return <span className={`badge ${badgeClass}`}>{status}</span>
}
