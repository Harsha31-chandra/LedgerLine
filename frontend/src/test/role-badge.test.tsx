import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RoleBadge } from '../components/RoleBadge'

describe('RoleBadge', () => {
  describe('Membership roles', () => {
    it('renders OWNER badge with badge-owner class', () => {
      render(<RoleBadge role="OWNER" type="membership" />)
      const badge = screen.getByText('OWNER')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('badge', 'badge-owner')
    })

    it('renders OPERATOR badge with badge-operator class', () => {
      render(<RoleBadge role="OPERATOR" type="membership" />)
      const badge = screen.getByText('OPERATOR')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('badge', 'badge-operator')
    })

    it('renders VIEWER badge with badge-viewer class', () => {
      render(<RoleBadge role="VIEWER" type="membership" />)
      const badge = screen.getByText('VIEWER')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('badge', 'badge-viewer')
    })
  })

  describe('User roles', () => {
    it('renders ADMIN badge with badge-admin class', () => {
      render(<RoleBadge role="ADMIN" type="user" />)
      const badge = screen.getByText('ADMIN')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('badge', 'badge-admin')
    })

    it('renders AUDITOR badge with badge-auditor class', () => {
      render(<RoleBadge role="AUDITOR" type="user" />)
      const badge = screen.getByText('AUDITOR')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('badge', 'badge-auditor')
    })

    it('renders HOLDER badge with badge-holder class', () => {
      render(<RoleBadge role="HOLDER" type="user" />)
      const badge = screen.getByText('HOLDER')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('badge', 'badge-holder')
    })
  })

  describe('Unknown role fallback', () => {
    it('renders unknown membership role with badge-neutral fallback class', () => {
      render(<RoleBadge role="UNKNOWN_ROLE" type="membership" />)
      const badge = screen.getByText('UNKNOWN_ROLE')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('badge', 'badge-neutral')
    })

    it('renders unknown user role with badge-neutral fallback class', () => {
      render(<RoleBadge role="SUPERUSER" type="user" />)
      const badge = screen.getByText('SUPERUSER')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('badge', 'badge-neutral')
    })
  })
})
