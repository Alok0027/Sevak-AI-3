# SevakAI District Dashboard

React 19 + Vite. District health dashboard for ANM/BMO/Admin roles (FR-08):
risk heatmap, four headline metrics, risk distribution chart, and the
unactioned-HIGH-risk-cases escalation list. Polls the backend every 60s.

Verified working end-to-end against the backend in this repo (login ->
metrics -> heatmap -> escalations all render with live data).

## Quick start

```bash
cd dashboard
npm install
cp -n .env.example .env     # -n: keeps an existing .env; point VITE_API_BASE_URL at your backend
npm run dev                 # http://localhost:5173 -- make sure ../backend is running too
```

`npm run build` produces a static `dist/` you can serve from anywhere
(FR-08.3: works in any modern browser, no install).

## Notes

- **Map tiles**: uses `react-leaflet` + OpenStreetMap tiles (free, no API
  key) rather than the Mapbox GL layer named in the SRS/deck. The data
  shape from `GET /dashboard/heatmap` (lat/lng/risk_level/patient_count) is
  the same either way -- swapping the tile layer for Mapbox later is
  contained to `src/components/RiskHeatmap.jsx`.
- **Auth**: JWT stored in `localStorage`, attached to every request by the
  axios interceptor in `src/api/client.js`. Demo logins: ANM `9999999901`,
  BMO `9999999902`, Admin `9999999903`, all PIN `1234` (see backend README).
- **RBAC**: the backend rejects an ASHA-role token on every route this app
  calls (403) -- there's no ASHA UI here on purpose, that's the mobile app's job.

## Layout

```
src/
  api/client.js              axios instance + typed calls to the FastAPI backend
  context/AuthContext.jsx    login state, persisted to localStorage
  pages/LoginPage.jsx        phone + PIN login
  pages/DashboardPage.jsx    fetches + polls metrics/heatmap/escalations
  components/
    MetricCard.jsx           one of the four FR-08.2 headline numbers
    RiskHeatmap.jsx          Leaflet map of risk_points
    EscalationList.jsx       FR-06.2 unactioned HIGH risk table
```

## Still to build (Week 3 per SRS section 10)

- BMO drill-down views (district -> block -> village).
- District/date-range filters on the heatmap (`district_id`, `date_range` query params already accepted by the backend).
- HMIS PDF download button wired to `GET /reports/hmis/{worker_id}/{month}/{year}/pdf`.
