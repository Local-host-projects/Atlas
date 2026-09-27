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

## Deploy on Pxxl

Push to GitHub, then Dashboard → Deploy → Import the repo.
`pxxl.toml` already sets the build: Python 3.12,
`pip install -r requirements.txt`,
`uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers`.

Set `SECRET_KEY` in Secrets, attach a managed PostgreSQL database
(`DATABASE_URL`), then redeploy.
