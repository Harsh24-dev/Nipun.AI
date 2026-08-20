-- Run once on Postgres init (docker-entrypoint-initdb.d)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
