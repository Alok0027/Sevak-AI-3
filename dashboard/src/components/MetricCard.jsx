/** FR-08.2: the four headline metrics, visible without scrolling. */
export default function MetricCard({ label, value, accent }) {
  return (
    <div className="metric-card" style={{ borderTopColor: accent }}>
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  );
}
