"""
Monetary validation and conversion utilities for LedgerLine.

Rules:
1. Monetary values are strictly stored as integer paise (minor units).
   Example: INR 500.00 = 50000 paise.
2. Binary floating-point arithmetic (float/double) is strictly prohibited.
3. Monetary inputs must be validated from decimal strings or integers.
"""
