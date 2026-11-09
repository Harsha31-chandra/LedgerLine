import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CurrencyAmount } from '../components/CurrencyAmount'

describe('CurrencyAmount', () => {
  it('renders positive amounts without sign prefix by default', () => {
    render(<CurrencyAmount amountPaise={5000} />)
    const el = screen.getByText('₹50.00')
    expect(el).toBeInTheDocument()
    expect(el).not.toHaveClass('amount-positive')
    expect(el).not.toHaveClass('amount-negative')
  })

  it('renders negative amounts with minus sign and negative styling', () => {
    render(<CurrencyAmount amountPaise={-5000} />)
    const el = screen.getByText('-₹50.00')
    expect(el).toBeInTheDocument()
    expect(el).toHaveClass('amount-negative')
  })

  it('renders positive amounts with explicit plus sign when showSign is true', () => {
    render(<CurrencyAmount amountPaise={5000} showSign={true} />)
    const el = screen.getByText('+₹50.00')
    expect(el).toBeInTheDocument()
    expect(el).toHaveClass('amount-positive')
  })

  it('renders negative amounts without duplicate minus sign when showSign is true', () => {
    render(<CurrencyAmount amountPaise={-5000} showSign={true} />)
    const el = screen.getByText('-₹50.00')
    expect(el).toBeInTheDocument()
    expect(el).toHaveClass('amount-negative')
    expect(screen.queryByText('--₹50.00')).not.toBeInTheDocument()
  })

  it('renders zero amounts neutrally', () => {
    render(<CurrencyAmount amountPaise={0} />)
    const el = screen.getByText('₹0.00')
    expect(el).toBeInTheDocument()
    expect(el).not.toHaveClass('amount-positive')
    expect(el).not.toHaveClass('amount-negative')
  })

  it('renders custom currencies correctly', () => {
    render(<CurrencyAmount amountPaise={-2550} currency="USD" />)
    const el = screen.getByText('-USD 25.50')
    expect(el).toBeInTheDocument()
    expect(el).toHaveClass('amount-negative')
  })

  it('renders Number.MAX_SAFE_INTEGER with exact fractional precision', () => {
    render(<CurrencyAmount amountPaise={Number.MAX_SAFE_INTEGER} />)
    const el = screen.getByText('₹9,00,71,99,25,47,409.91')
    expect(el).toBeInTheDocument()
  })

  it('renders -Number.MAX_SAFE_INTEGER with exact fractional precision and negative style', () => {
    render(<CurrencyAmount amountPaise={-Number.MAX_SAFE_INTEGER} />)
    const el = screen.getByText('-₹9,00,71,99,25,47,409.91')
    expect(el).toBeInTheDocument()
    expect(el).toHaveClass('amount-negative')
  })
})
