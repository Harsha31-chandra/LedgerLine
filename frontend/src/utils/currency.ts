/**
 * Currency and minor unit (paise) formatting utilities.
 */

export function formatPaise(paise: number, currency: string = 'INR'): string {
  const absAmount = Math.abs(paise) / 100
  const formattedNumber = absAmount.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })

  const symbol = currency === 'INR' ? '₹' : `${currency} `
  return `${symbol}${formattedNumber}`
}

export function parseRupeesToPaise(rupeesStr: string): number {
  const parsed = parseFloat(rupeesStr)
  if (isNaN(parsed) || parsed <= 0) return 0
  return Math.round(parsed * 100)
}
