# Database Migrations

This directory will contain incremental database migration scripts.

## Convention

Files should be named with a sequential prefix:

    001_initial_schema.sql
    002_add_column_xyz.sql
    003_create_table_abc.sql

## Initial Setup

For the initial database setup, use `db/schema.sql` directly:

    psql -d cat_power_solution -f db/schema.sql

## Migration Tool

When the team grows, consider adopting Alembic (SQLAlchemy) or Flyway
for automated migration management.
