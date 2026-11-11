-- LedgerLine Database Initialization Script
-- Automatically executed on first container launch via /docker-entrypoint-initdb.d/
-- Executed by PostgreSQL Bootstrap Administrator (ledgerline)

-- 1. Create dedicated test database if it does not already exist
SELECT 'CREATE DATABASE ledgerline_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ledgerline_test')\gexec

-- 2. Grant bootstrap administrator maintenance access
GRANT ALL PRIVILEGES ON DATABASE ledgerline_test TO ledgerline;

-- 3. Create dedicated non-superuser migration / schema-owner role
-- Enforces principle of least privilege: NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ledgerline_migrator') THEN
        CREATE ROLE ledgerline_migrator WITH LOGIN PASSWORD 'ledgerline_migrator_dev'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END
$$;

-- 4. Create dedicated non-superuser runtime application role
-- Enforces principle of least privilege: NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ledgerline_app') THEN
        CREATE ROLE ledgerline_app WITH LOGIN PASSWORD 'ledgerline_app_dev'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END
$$;

-- 5. Grant database connection privileges
GRANT CONNECT ON DATABASE ledgerline TO ledgerline_migrator, ledgerline_app;
GRANT CONNECT ON DATABASE ledgerline_test TO ledgerline_migrator, ledgerline_app;

-- 6. Configure schema ownership and least-privilege grants in development database
ALTER SCHEMA public OWNER TO ledgerline_migrator;
GRANT USAGE, CREATE ON SCHEMA public TO ledgerline_migrator;
GRANT USAGE ON SCHEMA public TO ledgerline_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ledgerline_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ledgerline_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ledgerline_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ledgerline_app;

-- 7. Configure schema ownership and least-privilege grants in test database
\c ledgerline_test
ALTER SCHEMA public OWNER TO ledgerline_migrator;
GRANT USAGE, CREATE ON SCHEMA public TO ledgerline_migrator;
GRANT USAGE ON SCHEMA public TO ledgerline_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ledgerline_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ledgerline_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ledgerline_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ledgerline_app;
