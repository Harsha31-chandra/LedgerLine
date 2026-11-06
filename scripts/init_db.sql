-- LedgerLine Database Initialization Script
-- Automatically executed on first container launch via /docker-entrypoint-initdb.d/

-- Create dedicated test database if it does not already exist
SELECT 'CREATE DATABASE ledgerline_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ledgerline_test')\gexec

-- Grant privileges to the ledgerline application user
GRANT ALL PRIVILEGES ON DATABASE ledgerline_test TO ledgerline;
