import { useEffect, useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchWorkerHistory } from "../api/client";
import { useSortableData } from "../hooks/useSortableData";

const RISK_COLOR = { HIGH: "#dc2626", MEDIUM: "#d97706", LOW: "#16a34a" };

export default function WorkerDetailPage() {
  const { workerId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [riskFilter, setRiskFilter] = useState("all");

  useEffect(() => {
    fetchWorkerHistory(workerId)
      .then(setData)
      .catch((err) => setError(err.response?.data?.detail || "Failed to load worker"));
  }, [workerId]);

  const visits = useMemo(() => {
    if (!data) return [];
    if (riskFilter === "all") return data.visits;
    return data.visits.filter((v) => v.risk_level === riskFilter);
  }, [data, riskFilter]);

  const { sorted, sortKey, direction, requestSort } = useSortableData(visits, "created_at", "desc");

  if (error) {
    return (
      <div className="dashboard-page">
        <button className="back-link" onClick={() => navigate(-1)}>&larr; Back</button>
        <p className="error">{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="dashboard-page">
        <p>Loading...</p>
      </div>
    );
  }

  const w = data.worker;

  return (
    <div className="dashboard-page">
      <button className="back-link" onClick={() => navigate(-1)}>&larr; Back to roster</button>

      <div className="detail-header">
        <div className="avatar avatar-lg">
          {w.name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase()}
        </div>
        <div>
          <h1>{w.name}</h1>
          <p className="subtitle">
            {w.phone} &middot; {w.sub_centre_id || "No sub-centre"} &middot; {w.language_pref.toUpperCase()}
          </p>
        </div>
      </div>

      <section className="metrics-row">
        <div className="metric-card" style={{ borderTopColor: "#2563eb" }}>
          <div className="metric-value">{w.total_patients}</div>
          <div className="metric-label">Patients Treated</div>
        </div>
        <div className="metric-card" style={{ borderTopColor: "#1f6f4a" }}>
          <div className="metric-value">{w.total_visits}</div>
          <div className="metric-label">Total Visits</div>
        </div>
        <div className="metric-card" style={{ borderTopColor: "#dc2626" }}>
          <div className="metric-value">{w.high_risk_count}</div>
          <div className="metric-label">HIGH Risk Flags</div>
        </div>
        <div className="metric-card" style={{ borderTopColor: "#d97706" }}>
          <div className="metric-value">{w.pending_followups}</div>
          <div className="metric-label">Pending Follow-ups</div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header-row">
          <h2>Visit History</h2>
          <select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}>
            <option value="all">All risk levels</option>
            <option value="HIGH">HIGH only</option>
            <option value="MEDIUM">MEDIUM only</option>
            <option value="LOW">LOW only</option>
          </select>
        </div>
        <div className="table-scroll">
          <table className="roster-table">
            <thead>
              <tr>
                <th className="sortable-th" onClick={() => requestSort("patient_name")}>
                  Patient{sortKey === "patient_name" && (direction === "asc" ? " ↑" : " ↓")}
                </th>
                <th className="sortable-th" onClick={() => requestSort("risk_level")}>
                  Risk{sortKey === "risk_level" && (direction === "asc" ? " ↑" : " ↓")}
                </th>
                <th className="sortable-th" onClick={() => requestSort("created_at")}>
                  Date{sortKey === "created_at" && (direction === "asc" ? " ↑" : " ↓")}
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((v) => (
                <tr key={v.visit_id} className="clickable-row" onClick={() => navigate(`/patients/${v.patient_id}`)}>
                  <td>{v.patient_name}</td>
                  <td>
                    <span className="pill" style={{ background: RISK_COLOR[v.risk_level] || "#888" }}>
                      {v.risk_level || "—"}
                    </span>
                  </td>
                  <td>{new Date(v.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={3} className="empty-state">No visits recorded.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
