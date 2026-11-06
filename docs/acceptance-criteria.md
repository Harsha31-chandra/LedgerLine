# Acceptance Criteria Checklist — LedgerLine

## Ten Mandatory Functional Requirements

- [ ] 1. Authentication and three roles (Admin, Account Holder, Auditor)
- [ ] 2. Accounts and balances
- [ ] 3. Money in and out (deposits, withdrawals, transfers)
- [ ] 4. Money conservation (net zero internal transfers)
- [ ] 5. No negative balances
- [ ] 6. Exactly-once idempotency with client key
- [ ] 7. Concurrency safety (atomic row locking)
- [ ] 8. Per-account statements (postings and refused attempts)
- [ ] 9. Per-account authorization (server-side entitlement check)
- [ ] 10. Automated proof (concurrency, conservation, replay, BOLA tests)
