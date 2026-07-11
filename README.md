# Campus Data Hub

An internal data aggregation and analytics dashboard.

## Stack

- **Frontend**: Vue 3 + TypeScript + Vite + Element Plus + ECharts + Pinia
- **Backend**: Python FastAPI + SQLite (read-only)
- **ETL**: Python pipeline (extract → transform → load → aggregate)

## Quick Start

```bash
# Backend
cd code/backend
pip install -r requirements.txt
python -m uvicorn backend.api.main:app --port 8000

# Frontend
cd code/frontend
pnpm install
npx vite --port 3006
```

Access: `http://localhost:3006`

## Project Structure

```
├── code/
│   ├── backend/          # FastAPI + ETL
│   │   ├── api/          # REST API routers
│   │   └── etl/          # Data pipeline
│   ├── frontend/         # Vue 3 SPA
│   └── scripts/          # Startup scripts
├── datasource/           # Source databases
└── docs/                 # Documentation
```

## Notes

- Read-only system. No write-back to source databases.
- Demo credentials are for local development only.
- Dev snapshot. Not intended for public distribution.
