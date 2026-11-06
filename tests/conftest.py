"""
Pytest configuration and fixtures.

SAFETY ENFORCEMENT:
Tests MUST connect to TEST_DATABASE_URL (ledgerline_test).
Tests MUST NEVER run against the development database (ledgerline).
Test fixtures will assert that 'ledgerline_test' is present in the connection URL
before executing any database setup, teardown, or transaction rollback.
"""
