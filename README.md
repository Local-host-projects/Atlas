# Atlas

Map-first operations dashboard for merchant service providers: a live map
(OpenStreetMap) with provider pins, floating desktop-style dashboard windows,
vertical-slice location strip, freehand/lasso area search, drag-to-reassign,
consumer request auto-routing, JWT auth with roles, and SQLite locally /
PostgreSQL in production.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000

Seed logins: `admin@atlas.local / admin123`, `manager@atlas.local / manager123`,
`provider@atlas.local / provider123`.

## Deploy on Railway

Push to GitHub, then Railway → New Project → Deploy from Repo → select this repo.
The `Procfile` already sets the start command
(`uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers`).

1. Add a PostgreSQL service (New → Database → PostgreSQL).
2. In the app service → Variables: add `SECRET_KEY` (long random string),
   `NIXPACKS_PYTHON_VERSION=3.12`, and reference the database as
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`.
3. Set the service health check path to `/health` and deploy.
