/**
 * Currency and minor unit (paise) formatting and parsing utilities.
 *
 * Distinctions between Backend and Frontend Precision Limits:
 * - Backend: PostgreSQL signed 64-bit integer (`BIGINT`), supporting up to
 *   2^63 - 1 = 9,223,372,036,854,775,807 paise (MAX_PAISE_AMOUNT).
 * - Frontend: JavaScript IEEE-754 double precision float representation of numbers,
 *   which is exact only up to 2^53 - 1 = 9,007,199,254,740,991 paise (FRONTEND_MAX_SAFE_PAISE,
 *   approx ₹90,071,992,547,409.91).
 *
 * To prevent silent precision loss (where values above 2^53 - 1 round to adjacent even integers),
 * `parseRupeesToPaise` strictly rejects any amount exceeding `FRONTEND_MAX_SAFE_PAISE`,
 * and `formatPaise` uses exact integer arithmetic (`BigInt`) to prevent float division rounding errors.
 */

/**
 * Backend maximum amount supported by PostgreSQL signed 64-bit BigInteger (2^63 - 1).
 */
export const BACKEND_MAX_PAISE_AMOUNT = 9_223_372_036_854_775_807n
export const MAX_PAISE_AMOUNT = BACKEND_MAX_PAISE_AMOUNT

/**
 * Frontend maximum amount safely representable by a JavaScript Number without precision loss (2^53 - 1).
 * Equal to 9,007,199,254,740,991 paise (~₹90.07 trillion).
 */
export const FRONTEND_MAX_SAFE_PAISE = BigInt(Number.MAX_SAFE_INTEGER)

/**
 * Format integer paise into localized currency string.
 * Uses BigInt integer division to eliminate float rounding errors on large safe-integer values.
 */
export function formatPaise(paise: number, currency: string = 'INR'): string {
  const isNegative = paise < 0
  const absPaise = Math.abs(paise)

  if (!Number.isFinite(absPaise)) {
    return currency === 'INR' ? '₹0.00' : `${currency} 0.00`
  }

  // Use integer arithmetic (BigInt) to avoid floating-point division precision loss near MAX_SAFE_INTEGER
  const paiseBig = BigInt(Math.trunc(absPaise))
  const wholeRupees = paiseBig / 100n
  const fractionPaise = paiseBig % 100n

  const formattedWhole = Number(wholeRupees).toLocaleString('en-IN')
  const formattedFraction = fractionPaise.toString().padStart(2, '0')
  const formattedNumber = `${formattedWhole}.${formattedFraction}`

  const symbol = currency === 'INR' ? '₹' : `${currency} `
  const sign = isNegative ? '-' : ''
  return `${sign}${symbol}${formattedNumber}`
}

/**
 * Parse a rupee string (plain or Indian comma grouped) into minor unit paise.
 * Enforces Number.MAX_SAFE_INTEGER to prevent silent floating-point precision loss.
 * Returns 0 on invalid, zero, negative, malformed, or precision-overflow inputs.
 */
export function parseRupeesToPaise(rupeesStr: string): number {
  if (typeof rupeesStr !== 'string') return 0
  const trimmed = rupeesStr.trim()
  if (!trimmed) return 0

  // Allow only digits, commas, and an optional single decimal separator.
  // Rejects explicit signs (+/-), letters, exponents, symbols, Infinity, NaN, whitespace within.
  if (!/^[0-9,]+(\.[0-9]+)?$/.test(trimmed)) return 0

  const parts = trimmed.split('.')
  if (parts.length > 2) return 0

  const intPart = parts[0]
  const decPart = parts.length === 2 ? parts[1] : ''

  // Validate decimal part: must be exactly 1 or 2 digits if present
  if (parts.length === 2 && !/^\d{1,2}$/.test(decPart)) return 0

  // Validate integer part:
  // 1) Unformatted plain integer: '0' or positive integer without leading zeros
  // 2) Indian comma-grouped: 1-2 digits, followed by zero or more 2-digit groups, ending with a 3-digit group
  const isPlainInt = /^(0|[1-9]\d*)$/.test(intPart)
  const isIndianCommaInt = /^[1-9]\d{0,1}(,\d{2})*,\d{3}$/.test(intPart)

  if (!isPlainInt && !isIndianCommaInt) return 0

  // Normalize decimal part to 2 digits without floating-point conversion
  const decPartNorm = decPart.padEnd(2, '0')
  const cleanInt = intPart.replace(/,/g, '')

  // Prevent parsing excessively long strings into BigInt
  if (cleanInt.length + decPartNorm.length > 18) return 0

  try {
    const paise = BigInt(cleanInt + decPartNorm)
    if (paise <= 0n || paise > FRONTEND_MAX_SAFE_PAISE) return 0
    return Number(paise)
  } catch {
    return 0
  }
}
