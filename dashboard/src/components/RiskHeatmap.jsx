import { MapContainer, TileLayer, CircleMarker, Tooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { TOKEN } from "./chartTheme";
import { Empty } from "./Surface";

/* FR-08.1: the district risk heatmap. One dot per village that has ever
 * had a visit, coloured and sized by the worst risk seen there.
 *
 * Coloured with the same tokens as every other risk read in this product
 * (chartTheme's riskHigh/riskMedium, and slate for LOW -- see
 * RiskBreakdownChart for why LOW is never green here). A dot's radius
 * carries patient_count, because two HIGH villages are not the same
 * fact when one has 1 case and the other has 11.
 *
 * The backend already collapses to one point per (village, risk_level)
 * pair (see dashboard.py's heatmap()), so a village with both a HIGH and
 * a LOW visit on record is two dots at the same coordinate -- drawn HIGH
 * last so it sits on top, since that is the one the supervisor has to
 * see first. */
const RISK_ORDER = { LOW: 0, MEDIUM: 1, HIGH: 2 };
const RISK_COLOR = { HIGH: TOKEN.riskHigh, MEDIUM: TOKEN.riskMedium, LOW: TOKEN.slate };

// Centred on Maharashtra, matching the backend's synthetic coordinate
// range (_MH_LAT_RANGE/_MH_LNG_RANGE in dashboard.py) until the district
// pilot has real GPS on file -- see that function's docstring.
const DEFAULT_CENTER = [19.5, 74.7];
const DEFAULT_ZOOM = 7;

function radiusFor(count) {
  // Area, not radius, should scale with count, or ten cases reads as a
  // hundred times the dot of one. sqrt keeps it perceptual; clamped so a
  // single-patient village stays clickable and a big one doesn't swallow
  // its neighbours.
  return Math.max(7, Math.min(26, 7 + Math.sqrt(count) * 5));
}

export default function RiskHeatmap({ points }) {
  if (!points) {
    return <div className="heatmap-loading">Loading map…</div>;
  }
  if (points.length === 0) {
    return <Empty>No classified visits yet — villages will appear here as ASHAs record them.</Empty>;
  }

  const sorted = [...points].sort((a, b) => RISK_ORDER[a.risk_level] - RISK_ORDER[b.risk_level]);

  return (
    <MapContainer
      center={DEFAULT_CENTER}
      zoom={DEFAULT_ZOOM}
      scrollWheelZoom={false}
      className="heatmap-map"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {sorted.map((p, i) => (
        <CircleMarker
          key={`${p.village}-${p.risk_level}-${i}`}
          center={[p.lat, p.lng]}
          radius={radiusFor(p.patient_count)}
          pathOptions={{
            color: RISK_COLOR[p.risk_level] || TOKEN.slate,
            fillColor: RISK_COLOR[p.risk_level] || TOKEN.slate,
            fillOpacity: 0.55,
            weight: 1.5,
          }}
        >
          <Tooltip direction="top" offset={[0, -4]}>
            <strong>{p.village || "Unknown village"}</strong>
            <br />
            {p.risk_level} risk · {p.patient_count} {p.patient_count === 1 ? "patient" : "patients"}
          </Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
