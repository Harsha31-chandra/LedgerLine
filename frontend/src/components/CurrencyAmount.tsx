import { formatPaise } from '../utils/currency'

interface CurrencyAmountProps {
  amountPaise: number
  currency?: string
  showSign?: boolean
  className?: string
}

export function CurrencyAmount({
  amountPaise,
  currency = 'INR',
  showSign = false,
  className = '',
}: CurrencyAmountProps) {
  const formatted = formatPaise(amountPaise, currency)
  const isNegative = amountPaise < 0
  const isPositive = amountPaise > 0

  let signPrefix = ''
  let signClass = ''

  if (showSign) {
    if (isPositive) {
      signPrefix = '+'
      signClass = 'amount-positive'
    } else if (isNegative) {
      signPrefix = '-'
      signClass = 'amount-negative'
    }
  }

  return (
    <span className={`tabular-numbers font-medium ${signClass} ${className}`}>
      {signPrefix}
      {formatted}
    </span>
  )
}
