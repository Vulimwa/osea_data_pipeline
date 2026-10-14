# OSEAS map UI (Kano plains pilot)

Reads Bravin’s API at `/api/v1/oseas` (Vite proxies to `http://127.0.0.1:3000`).

```powershell
# terminal 1 — API (use pooler DATABASE_URL, not IPv6-only db.*)
npm run start

# terminal 2 — UI
npm run dev:ui
```

Open http://127.0.0.1:5173. Default view is the Kano plains bbox; orange markers are `osm_kano_pilot`.
