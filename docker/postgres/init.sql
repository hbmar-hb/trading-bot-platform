-- Extensiones necesarias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID generación
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- Funciones crypto adicionales

-- Las tablas las crea Alembic con las migraciones
-- Este fichero solo prepara extensiones que Alembic necesita disponibles
