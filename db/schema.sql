-- ============================================================
-- CAT Power Solution — Database Schema
-- PostgreSQL 15+
-- Execute: psql -d cat_power_solution -f db/schema.sql
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- TABLE: projects
-- Stores saved sizing projects per user.
-- Row Level Security: each user only sees their own projects.
-- ============================================================

CREATE TABLE IF NOT EXISTS projects (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_email          VARCHAR(255) NOT NULL,
    user_name           VARCHAR(255),
    client_name         VARCHAR(500),
    project_location    VARCHAR(255),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    inputs_json         JSONB NOT NULL,         -- SizingInput completo
    results_json        JSONB,                  -- SizingResult completo (NULL si no corrió)
    tool_version        VARCHAR(20),
    pdf_executive_url   VARCHAR(1000),          -- Azure Blob SAS URL
    pdf_full_url        VARCHAR(1000),          -- Azure Blob SAS URL
    tags                TEXT[] DEFAULT '{}',    -- etiquetas libres del usuario
    notes               TEXT
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_projects_user_email ON projects(user_email);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_client ON projects(client_name);

-- Trigger: actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Row Level Security
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;

-- Política: cada usuario solo ve sus proyectos
-- La app setea app.current_user antes de cada query
CREATE POLICY user_isolation ON projects
    USING (user_email = current_setting('app.current_user', TRUE));

-- Admins pueden ver todos (la app setea app.is_admin = 'true' para admins)
CREATE POLICY admin_override ON projects
    USING (current_setting('app.is_admin', TRUE) = 'true');


-- ============================================================
-- TABLE: audit_log
-- Every API request logged with user, action, timing, status.
-- Required: 90-day retention per CAT security policy.
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    user_email      VARCHAR(255),               -- NULL si no autenticado
    user_role       VARCHAR(20),                -- demo | full | admin
    ip_address      INET,
    method          VARCHAR(10),                -- GET | POST | etc.
    endpoint        VARCHAR(500),
    action          VARCHAR(100),               -- 'sizing_run' | 'pdf_download' | 'login' | etc.
    project_id      UUID,                       -- si aplica
    input_hash      VARCHAR(64),               -- SHA-256 del body (no el body mismo)
    duration_ms     INTEGER,
    status_code     INTEGER,
    error_message   TEXT                        -- solo si status >= 400
);

-- Índice para queries de auditoría (por fecha y usuario)
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_email, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action, timestamp DESC);

-- Política de retención: el campo timestamp permite limpiar con:
-- DELETE FROM audit_log WHERE timestamp < NOW() - INTERVAL '90 days';
-- Configurar como cron job o Azure Logic App.


-- ============================================================
-- TABLE: equipment_pricing
-- Generator and equipment pricing.
-- Updated quarterly from CAT pricing team (manual CSV import initially).
-- ============================================================

CREATE TABLE IF NOT EXISTS equipment_pricing (
    model_name          VARCHAR(100) PRIMARY KEY,
    cost_usd_kw         DECIMAL(10,2),          -- CAPEX generador $/kW
    install_usd_kw      DECIMAL(10,2),          -- instalación $/kW
    rental_usd_kw_mes   DECIMAL(10,2),          -- tarifa rental $/kW-mes
    last_updated        DATE DEFAULT CURRENT_DATE,
    updated_by          VARCHAR(255),
    source              VARCHAR(200),            -- 'SAP_EXPORT_2025Q1' | 'MANUAL' | etc.
    notes               TEXT
);

-- Datos iniciales (placeholders — actualizar con precios reales)
INSERT INTO equipment_pricing (model_name, cost_usd_kw, install_usd_kw, source) VALUES
    ('XGC1900',   775, 300, 'INITIAL_PLACEHOLDER'),
    ('G3520FR',   800, 350, 'INITIAL_PLACEHOLDER'),
    ('G3520K',    900, 375, 'INITIAL_PLACEHOLDER'),
    ('G3516H',    850, 350, 'INITIAL_PLACEHOLDER'),
    ('CG260-16',  820, 400, 'INITIAL_PLACEHOLDER'),
    ('C175-20',   780, 380, 'INITIAL_PLACEHOLDER'),
    ('Titan 130', 650, 500, 'INITIAL_PLACEHOLDER'),
    ('G20CM34',   700, 450, 'INITIAL_PLACEHOLDER')
ON CONFLICT (model_name) DO NOTHING;


-- ============================================================
-- APPLICATION USER (crear en psql como admin)
-- ============================================================
-- Ejecutar manualmente como superuser:
--
-- CREATE USER cps_app WITH PASSWORD '{password}';
-- GRANT CONNECT ON DATABASE cat_power_solution TO cps_app;
-- GRANT USAGE ON SCHEMA public TO cps_app;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cps_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cps_app;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public
--     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cps_app;
-- ============================================================
