import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MapContainer, TileLayer, CircleMarker, Tooltip, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { TOKEN } from "./chartTheme";
import { Empty } from "./Surface";

/* FR-08.1: the district risk heatmap.
 *
 * One dot per village, placed where the village actually is (see
 * backend/app/services/geo.py -- a village the gazetteer doesn't know is
 * still drawn, but says so rather than passing a placeholder off as a
 * survey coordinate). Colour is the worst risk currently open there;
 * size is how many patients are on the books.
 *
 * A map on a dashboard has to answer a question the four stat tiles
 * above it can't, or it is decoration. The question here is "where do I
 * send someone tomorrow" -- which is why every dot opens the village's
 * actual caseload: the HIGH/MEDIUM/LOW split, when it was last visited,
 * and a way through to those exact patients. A supervisor who can only
 * hover and read a name would be better served by a table.
 */
const RISK_ORDER = { HIGH: 0, MEDIUM: 1, LOW: 2 };
const RISK_COLOR = { HIGH: TOKEN.riskHigh, MEDIUM: TOKEN.riskMedium, LOW: TOKEN.slate };
const RISK_LABEL = { HIGH: "HIGH", MEDIUM: "MEDIUM", LOW: "LOW" };

// Pune district. Only used when there is exactly one village to show and
// bounds would be a point rather than a box.
const FALLBACK_CENTRE = [18.62, 74.1];

function radiusFor(count) {
  // Area, not radius, scales with caseload -- ten patients should not
  // read as a hundred times the dot of one. Clamped so a single-patient
  // village stays clickable and a large one doesn't swallow neighbours.
  return Math.max(7, Math.min(26, 7 + Math.sqrt(count) * 4.5));
}

function fmtDate(iso) {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso)) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return new Date(iso).toLocaleDateString();
}

/** The village's caseload as one bar. Proportions, not counts -- the
 *  counts are spelled out underneath, and a bar that tried to carry both
 *  would do neither well. */
function SplitBar({ point }) {
  const total = point.patient_count || 1;
  const segments = ["HIGH", "MEDIUM", "LOW"].map((level) => ({
    level,
    count: point[`${level.toLowerCase()}_count`] || 0,
  }));
  return (
    <div className="village-split" role="img" aria-label={segments.map((s) => `${s.count} ${s.level}`).join(", ")}>
      {segments
        .filter((s) => s.count > 0)
        .map((s) => (
          <span
            key={s.level}
            className="village-split-seg"
            style={{ width: `${(s.count / total) * 100}%`, background: RISK_COLOR[s.level] }}
          />
        ))}
    </div>
  );
}

export default function RiskHeatmap({ points }) {
  const navigate = useNavigate();
  const [selected, setSelected] = useState(null);

  // Framed once, from the first load that has data. Recomputing on every
  // poll would yank the map back to the district while a supervisor is
  // reading a village she zoomed into.
  const bounds = useMemo(() => {
    if (!points || points.length < 2) return null;
    return points.map((p) => [p.lat, p.lng]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points && points.length > 0]);

  const summary = useMemo(() => {
    if (!points?.length) return null;
    const patients = points.reduce((n, p) => n + p.patient_count, 0);
    const high = points.filter((p) => p.high_count > 0);
    const worst = [...high].sort((a, b) => b.high_count - a.high_count)[0];
    return { villages: points.length, patients, highVillages: high.length, worst };
  }, [points]);

  if (!points) {
    return <div className="heatmap-loading">Loading map…</div>;
  }
  if (points.length === 0) {
    return <Empty>No classified visits yet — villages appear here as ASHAs record them.</Empty>;
  }

  // Worst last so a HIGH village is drawn on top of its quieter
  // neighbours, never hidden behind one.
  const drawOrder = [...points].sort((a, b) => RISK_ORDER[b.risk_level] - RISK_ORDER[a.risk_level]);
  const single = points.length === 1 ? [points[0].lat, points[0].lng] : null;

  return (
    <div className="heatmap-wrap">
      <div className="heatmap-summary">
        <span>
          <strong>{summary.villages}</strong> {summary.villages === 1 ? "village" : "villages"}
        </span>
        <span>
          <strong>{summary.patients}</strong> patients on the books
        </span>
        <span className={summary.highVillages ? "is-high" : undefined}>
          <strong>{summary.highVillages}</strong> with open HIGH-risk cases
        </span>
        {summary.worst && (
          <span className="heatmap-summary-worst">
            Worst: <strong>{summary.worst.village}</strong> ({summary.worst.high_count} HIGH)
          </span>
        )}
      </div>

      <div className="heatmap-canvas">
        <MapContainer
          bounds={bounds || undefined}
          boundsOptions={{ padding: [40, 40], maxZoom: 11 }}
          center={bounds ? undefined : single || FALLBACK_CENTRE}
          zoom={bounds ? undefined : 11}
          scrollWheelZoom={false}
          className="heatmap-map"
        >
          {/* Carto's light basemap rather than standard OSM: OSM's roads,
              landuse and labels are the same weight and saturation as the
              risk dots, so the data ends up competing with the map for
              attention. This one is built to sit underneath data. */}
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          />

          {drawOrder.map((p) => {
            const colour = RISK_COLOR[p.risk_level] || TOKEN.slate;
            const isSelected = selected === p.village;
            return (
              <CircleMarker
                key={p.village}
                center={[p.lat, p.lng]}
                radius={radiusFor(p.patient_count)}
                eventHandlers={{
                  popupopen: () => setSelected(p.village),
                  popupclose: () => setSelected((v) => (v === p.village ? null : v)),
                }}
                pathOptions={{
                  color: colour,
                  fillColor: colour,
                  fillOpacity: isSelected ? 0.75 : 0.5,
                  weight: isSelected ? 3 : 1.5,
                  // A village whose position is a placeholder is drawn
                  // hollow-dashed, so nobody reads its dot as a surveyed
                  // location (see geo.locate).
                  dashArray: p.approximate_location ? "4 3" : undefined,
                }}
              >
                <Tooltip direction="top" offset={[0, -4]}>
                  <strong>{p.village || "Unknown village"}</strong>
                  <br />
                  {p.patient_count} {p.patient_count === 1 ? "patient" : "patients"}
                  {p.high_count > 0 && ` · ${p.high_count} HIGH`}
                  <br />
                  <span className="tooltip-hint">Click for the breakdown</span>
                </Tooltip>

                <Popup className="village-popup" minWidth={232}>
                  <div className="village-card">
                    <div className="village-card-head">
                      <strong>{p.village || "Unknown village"}</strong>
                      <span className={`risk-tag tone-${p.risk_level.toLowerCase()}`}>
                        {RISK_LABEL[p.risk_level]}
                      </span>
                    </div>

                    <SplitBar point={p} />
                    <div className="village-legend">
                      {["HIGH", "MEDIUM", "LOW"].map((level) => (
                        <span key={level}>
                          <i style={{ background: RISK_COLOR[level] }} />
                          {p[`${level.toLowerCase()}_count`]} {level}
                        </span>
                      ))}
                    </div>

                    <dl className="village-facts">
                      <div>
                        <dt>Patients</dt>
                        <dd>{p.patient_count}</dd>
                      </div>
                      <div>
                        <dt>Visits</dt>
                        <dd>{p.visit_count}</dd>
                      </div>
                      <div>
                        <dt>Last seen</dt>
                        <dd>{fmtDate(p.last_visit_at)}</dd>
                      </div>
                    </dl>

                    {p.approximate_location && (
                      <p className="village-approx">
                        Position approximate — this village isn’t in the district gazetteer yet.
                      </p>
                    )}

                    <button
                      type="button"
                      className="btn-submit village-cta"
                      onClick={() => navigate(`/patients?village=${encodeURIComponent(p.village)}`)}
                    >
                      View these {p.patient_count} {p.patient_count === 1 ? "patient" : "patients"} →
                    </button>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>

        <div className="heatmap-key">
          <span className="heatmap-key-title">Worst open risk</span>
          {["HIGH", "MEDIUM", "LOW"].map((level) => (
            <span key={level} className="heatmap-key-row">
              <i style={{ background: RISK_COLOR[level] }} />
              {level}
            </span>
          ))}
          <span className="heatmap-key-note">Dot size = patients · dashed = position approximate</span>
        </div>
      </div>
    </div>
  );
}
