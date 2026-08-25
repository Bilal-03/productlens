DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'migration_owner') THEN
    CREATE ROLE migration_owner LOGIN NOINHERIT CREATEROLE PASSWORD 'migration_owner_local';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_writer') THEN
    CREATE ROLE app_writer LOGIN PASSWORD 'app_writer_local';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_reader') THEN
    CREATE ROLE analytics_reader LOGIN PASSWORD 'analytics_reader_local';
  END IF;
END $$;

GRANT CREATE ON DATABASE productlens TO migration_owner;
GRANT USAGE, CREATE ON SCHEMA public TO migration_owner;
GRANT analytics_reader TO migration_owner WITH ADMIN OPTION;
GRANT app_writer TO migration_owner WITH ADMIN OPTION;
