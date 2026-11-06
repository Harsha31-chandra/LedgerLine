# THREATS.md — LedgerLine Security Threat Model

## System Summary

LedgerLine is a simulated internal money-movement system. It processes deposits, withdrawals and account-to-account transfers using double-entry ledger postings. This is an assessment project — no real money or bank connections are involved.

### Deliberately Out of Scope

- Real bank integrations or payment gateways
- Multi-currency support
- Mobile applications
- AI agents or automated trading

## Assets

| Asset | Description |
|-------|-------------|
| Account balances | Integer paise values representing simulated money |
| Ledger entries | Append-only financial postings |
| Credentials | Hashed passwords, session tokens |
| Audit history | Records of all actions and refused attempts |
| Idempotency records | Replay protection keys and stored responses |

## Trust Boundaries

*To be documented as implementation progresses.*

## Threat Actors

*To be documented as implementation progresses.*

## Threat Register

*To be populated with specific threats, attack paths, mitigations, test IDs and residual risks.*

## Residual Risks

*To be stated honestly for threats not fully mitigated.*
