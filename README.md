# CAT Power Solution

**Prime power sizing platform for AI Data Centers and Industrial projects**
LEPS Global · Caterpillar Electric Power

[![Tests](https://img.shields.io/badge/tests-127%20passing-brightgreen)]()
[![Version](https://img.shields.io/badge/version-3.2.0-blue)]()
[![Python](https://img.shields.io/badge/python-3.11-blue)]()

---

## Quick Start (desarrollo local)

    # 1. Clonar
    git clone https://dev.azure.com/caterpillar/LEPS-Tools/_git/cat-power-solution

    # 2. Configurar variables de entorno
    cp .env.example .env
    # Editar .env — para desarrollo local solo ANTHROPIC_API_KEY es necesaria

    # 3. Levantar con Docker Compose
    docker-compose up

    # 4. Verificar
    curl http://localhost:8000/api/v1/health
    # → {"status": "ok", "version": "3.2.0", "environment": "development"}

    # 5. API docs interactiva
    open http://localhost:8000/api/docs

## Running Tests

    pip install -r requirements.txt
    pytest tests/ -v
    # → 127 passed

## Architecture

    core/        — Calculation engine (CAT IP) — 16 functions, stateless
    api/         — FastAPI REST API — 6 routers, Pydantic validation
    db/          — PostgreSQL schema — projects, audit_log, equipment_pricing
    tests/       — pytest suite — engine + API smoke tests

Full technical documentation: docs/it-handoff.md

## Deployment

See docs/it-handoff.md — Section 5.

Azure App Service — Python 3.11 — uvicorn
Authentication: Microsoft Entra ID (caterpillar.com tenant)
Database: Azure PostgreSQL Flexible Server

## Owner

Francisco Saraiva — Power Plant Design Engineer, LEPS Global
francisco.saraiva@cat.com
