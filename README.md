# Campus Data Hub

An internal data aggregation and analytics dashboard.

## Stack

- **Frontend**: Vue 3 + TypeScript + Vite + Element Plus + ECharts + Pinia
- **Backend**: Python FastAPI + SQLite (read-only)
- **ETL**: Python pipeline (extract → transform → load → aggregate)

## Quick Start

```bash
# 1. Install backend dependencies
cd code/backend
pip install -r requirements.txt
cd ..

# 2. Initialize data. Teaching sources are used when present; otherwise a
#    compact anonymized dataset is generated for all nine basic reports.
# Windows: scripts\init.bat
# macOS / Linux / Git-Bash:
bash scripts/init.sh

# 3. Start the frontend and backend in separate shells
cd frontend
pnpm install
npx vite --port 3006
# another shell, from code/:
python -m uvicorn backend.api.main:app --port 8000
```

Access: `http://localhost:3006` · demo login: `admin / Demo@2026`.
After initialization, a source-only GitHub checkout shows four top-level menus and query/export results for all nine reports under “基础报表”.

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
