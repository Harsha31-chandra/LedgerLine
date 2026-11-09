import { describe, it, expect } from 'vitest'
import {
  formatPaise,
  parseRupeesToPaise,
  FRONTEND_MAX_SAFE_PAISE,
  BACKEND_MAX_PAISE_AMOUNT,
} from '../utils/currency'

describe('parseRupeesToPaise', () => {
  describe('Indian comma grouping', () => {
    it('parses valid Indian comma-formatted amounts with decimals', () => {
      expect(parseRupeesToPaise('1,23,456.78')).toBe(12345678)
      expect(parseRupeesToPaise('10,000.00')).toBe(1000000)
      expect(parseRupeesToPaise('12,34,567.89')).toBe(123456789)
      expect(parseRupeesToPaise('1,00,00,000.50')).toBe(1000000050)
      expect(parseRupeesToPaise('12,34,56,789.50')).toBe(12345678950)
    })

    it('parses valid Indian comma-formatted integer amounts without decimals', () => {
      expect(parseRupeesToPaise('1,000')).toBe(100000)
      expect(parseRupeesToPaise('10,000')).toBe(1000000)
      expect(parseRupeesToPaise('1,00,000')).toBe(10000000)
      expect(parseRupeesToPaise('1,00,00,000')).toBe(1000000000)
    })

    it('parses very large valid Indian comma-formatted rupee amounts within safe integer limit', () => {
      // 100 Crore = ₹1,00,00,00,000.00 -> 100,000,000,000 paise
      expect(parseRupeesToPaise('1,00,00,00,000.00')).toBe(100000000000)
      // 10,000 Crore = ₹10,00,00,00,000.00 -> 1,000,000,000,000 paise
      expect(parseRupeesToPaise('10,00,00,00,000.00')).toBe(1000000000000)
      // 1,00,000 Crore (₹1 Trillion) = ₹1,00,00,00,00,000.00 -> 10,000,000,000,000 paise
      expect(parseRupeesToPaise('1,00,00,00,00,000.00')).toBe(10000000000000)
      // Large Indian amount (₹90 Billion) -> 9,000,000,000,000 paise
      expect(parseRupeesToPaise('90,00,00,00,000.00')).toBe(9000000000000)
      // Large Indian amount (₹900 Billion) -> 90,000,000,000,000 paise
      expect(parseRupeesToPaise('9,00,00,00,00,000.00')).toBe(90000000000000)
    })
  })

  describe('Unformatted plain amounts', () => {
    it('parses standard plain amounts correctly', () => {
      expect(parseRupeesToPaise('0.01')).toBe(1)
      expect(parseRupeesToPaise('10.10')).toBe(1010)
      expect(parseRupeesToPaise('99.99')).toBe(9999)
      expect(parseRupeesToPaise('100.25')).toBe(10025)
      expect(parseRupeesToPaise('1')).toBe(100)
      expect(parseRupeesToPaise('100')).toBe(10000)
      expect(parseRupeesToPaise('10000')).toBe(1000000)
      expect(parseRupeesToPaise('12345678')).toBe(1234567800)
    })
  })

  describe('One- and two-decimal amounts', () => {
    it('handles single-decimal and double-decimal amounts with proper minor unit conversion', () => {
      expect(parseRupeesToPaise('0.1')).toBe(10)
      expect(parseRupeesToPaise('10.5')).toBe(1050)
      expect(parseRupeesToPaise('100.2')).toBe(10020)
      expect(parseRupeesToPaise('0.01')).toBe(1)
      expect(parseRupeesToPaise('10.05')).toBe(1005)
      expect(parseRupeesToPaise('10.10')).toBe(1010)
      expect(parseRupeesToPaise('10.50')).toBe(1050)
    })
  })

  describe('Invalid comma grouping rejection', () => {
    it('rejects malformed and non-Indian comma groupings', () => {
      // Western 3-digit grouping
      expect(parseRupeesToPaise('123,456.78')).toBe(0)
      expect(parseRupeesToPaise('1,000,000')).toBe(0)
      // Malformed separator positions
      expect(parseRupeesToPaise('1,2,3')).toBe(0)
      expect(parseRupeesToPaise('10,0')).toBe(0)
      expect(parseRupeesToPaise('1,2345')).toBe(0)
      expect(parseRupeesToPaise(',100')).toBe(0)
      expect(parseRupeesToPaise('100,')).toBe(0)
      expect(parseRupeesToPaise('10,,000')).toBe(0)
      expect(parseRupeesToPaise('0,100')).toBe(0)
      expect(parseRupeesToPaise('10,000,00')).toBe(0)
      expect(parseRupeesToPaise('1,00,00')).toBe(0)
    })
  })

  describe('More than two decimal places rejection', () => {
    it('rejects amounts exceeding two decimal precision without rounding', () => {
      expect(parseRupeesToPaise('10.123')).toBe(0)
      expect(parseRupeesToPaise('0.001')).toBe(0)
      expect(parseRupeesToPaise('1,23,456.789')).toBe(0)
      expect(parseRupeesToPaise('10.100')).toBe(0)
      expect(parseRupeesToPaise('0.000')).toBe(0)
    })
  })

  describe('Zero, negative, whitespace and non-numeric rejection', () => {
    it('rejects zero amounts', () => {
      expect(parseRupeesToPaise('0')).toBe(0)
      expect(parseRupeesToPaise('0.0')).toBe(0)
      expect(parseRupeesToPaise('0.00')).toBe(0)
      expect(parseRupeesToPaise('-0')).toBe(0)
    })

    it('rejects negative amounts', () => {
      expect(parseRupeesToPaise('-10')).toBe(0)
      expect(parseRupeesToPaise('-0.01')).toBe(0)
      expect(parseRupeesToPaise('-1,23,456.78')).toBe(0)
    })

    it('rejects empty, whitespace-only and invalid string inputs', () => {
      expect(parseRupeesToPaise('')).toBe(0)
      expect(parseRupeesToPaise('   ')).toBe(0)
      expect(parseRupeesToPaise('abc')).toBe(0)
      expect(parseRupeesToPaise('₹100')).toBe(0)
      expect(parseRupeesToPaise('10.0.0')).toBe(0)
      expect(parseRupeesToPaise('10.')).toBe(0)
      expect(parseRupeesToPaise('.5')).toBe(0)
      expect(parseRupeesToPaise('+100')).toBe(0)
    })

    it('rejects special numeric values (Infinity, NaN)', () => {
      expect(parseRupeesToPaise('Infinity')).toBe(0)
      expect(parseRupeesToPaise('-Infinity')).toBe(0)
      expect(parseRupeesToPaise('NaN')).toBe(0)
    })
  })

  describe('Number.MAX_SAFE_INTEGER boundary enforcement', () => {
    it('accepts exact Number.MAX_SAFE_INTEGER in unformatted and Indian comma format', () => {
      // 9,007,199,254,740,991 paise = 90071992547409.91 rupees = ₹90,071,992,547,409.91
      expect(FRONTEND_MAX_SAFE_PAISE).toBe(9007199254740991n)
      expect(parseRupeesToPaise('90071992547409.91')).toBe(Number.MAX_SAFE_INTEGER)
      expect(parseRupeesToPaise('9,00,71,99,25,47,409.91')).toBe(Number.MAX_SAFE_INTEGER)
    })

    it('accepts safe integer amounts slightly below Number.MAX_SAFE_INTEGER', () => {
      // 90,071,992,547,409.90 rupees -> 9007199254740990 paise
      expect(parseRupeesToPaise('90071992547409.90')).toBe(Number.MAX_SAFE_INTEGER - 1)
      expect(parseRupeesToPaise('9,00,71,99,25,47,409.90')).toBe(Number.MAX_SAFE_INTEGER - 1)
      // Integer rupees amount (without paise)
      expect(parseRupeesToPaise('90071992547409')).toBe(9007199254740900)
      expect(parseRupeesToPaise('9,00,71,99,25,47,409')).toBe(9007199254740900)
    })

    it('rejects amounts exactly one paise above Number.MAX_SAFE_INTEGER', () => {
      // 90,071,992,547,409.92 rupees -> 9007199254740992 paise (exceeds 2^53 - 1)
      expect(parseRupeesToPaise('90071992547409.92')).toBe(0)
      expect(parseRupeesToPaise('9,00,71,99,25,47,409.92')).toBe(0)
    })

    it('rejects amounts one rupee above Number.MAX_SAFE_INTEGER boundary', () => {
      expect(parseRupeesToPaise('90071992547410.00')).toBe(0)
      expect(parseRupeesToPaise('90071992547410')).toBe(0)
    })

    it('rejects backend PostgreSQL BigInteger limit on frontend to prevent silent precision loss', () => {
      // PostgreSQL signed 64-bit BigInt max: 9,223,372,036,854,775,807 paise (2^63 - 1)
      expect(BACKEND_MAX_PAISE_AMOUNT).toBe(9223372036854775807n)
      expect(parseRupeesToPaise('92233720368547758.07')).toBe(0)
      expect(parseRupeesToPaise('92233720368547758.08')).toBe(0)
      expect(parseRupeesToPaise('999999999999999999999999999')).toBe(0)
    })
  })
})

describe('formatPaise', () => {
  it('formats positive paise values with Indian grouping and INR symbol', () => {
    expect(formatPaise(5000)).toBe('₹50.00')
    expect(formatPaise(12345678)).toBe('₹1,23,456.78')
    expect(formatPaise(100)).toBe('₹1.00')
    expect(formatPaise(1)).toBe('₹0.01')
    expect(formatPaise(0)).toBe('₹0.00')
  })

  it('formats negative paise values retaining negative sign', () => {
    expect(formatPaise(-5000)).toBe('-₹50.00')
    expect(formatPaise(-1)).toBe('-₹0.01')
    expect(formatPaise(-12345678)).toBe('-₹1,23,456.78')
  })

  it('formats Number.MAX_SAFE_INTEGER without losing fractional precision', () => {
    // 9,007,199,254,740,991 paise = ₹9,00,71,99,25,47,409.91
    // (Standard float division / 100 rounds to .90; integer division preserves exact .91)
    expect(formatPaise(Number.MAX_SAFE_INTEGER)).toBe('₹9,00,71,99,25,47,409.91')
    expect(formatPaise(-Number.MAX_SAFE_INTEGER)).toBe('-₹9,00,71,99,25,47,409.91')
  })

  it('supports custom currency codes for positive, negative, and large amounts', () => {
    expect(formatPaise(5000, 'USD')).toBe('USD 50.00')
    expect(formatPaise(-5000, 'USD')).toBe('-USD 50.00')
    expect(formatPaise(100000, 'EUR')).toBe('EUR 1,000.00')
    expect(formatPaise(-100000, 'EUR')).toBe('-EUR 1,000.00')
    expect(formatPaise(Number.MAX_SAFE_INTEGER, 'USD')).toBe('USD 9,00,71,99,25,47,409.91')
    expect(formatPaise(-Number.MAX_SAFE_INTEGER, 'USD')).toBe('-USD 9,00,71,99,25,47,409.91')
  })
})
