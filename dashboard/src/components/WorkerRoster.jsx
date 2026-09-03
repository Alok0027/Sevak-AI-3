import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useSortableData } from "../hooks/useSortableData";

const COLUMNS = [
  { key: "name", label: "Worker" },
  { key: "sub_centre_id", label: "Sub-centre", bmoOnly: true },
  { key: "total_patients", label: "Patients" },
  { key: "total_visits", label: "Visits" },
  { key: "high_risk_count", label: "High" },
  { key: "medium_risk_count", label: "Medium" },
  { key: "pending_followups", label: "Pending" },
  { key: "last_visit_at", label: "Last Visit" },
];

function initials(name) {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

/** FR-08 "worker performance metrics": sortable, filterable roster --
 * clicking a worker drills into their full history (WorkerDetailPage). */
export default function WorkerRoster({ workers, showSubCentre }) {
  const navigate = useNavigate();
  const [riskFilter, setRiskFilter] = useState("all");
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    return workers.filter((w) => {
      if (search && !w.name.toLowerCase().includes(search.toLowerCase())) return false;
      if (riskFilter === "high" && w.high_risk_count === 0) return false;
      if (riskFilter === "pending" && w.pending_followups === 0) return false;
      if (riskFilter === "inactive" && w.total_visits > 0) return false;
      return true;
    });
  }, [workers, search, riskFilter]);

  const { sorted, sortKey, direction, requestSort } = useSortableData(filtered, "total_visits", "desc");
  const columns = COLUMNS.filter((c) => !c.bmoOnly || showSubCentre);

  return (
    <div>
      <div className="roster-filters">
        <input
          className="roster-search"
          placeholder="Search worker name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}>
          <option value="all">All workers</option>
          <option value="high">Has HIGH risk cases</option>
          <option value="pending">Has pending follow-ups</option>
          <option value="inactive">No visits logged yet</option>
        </select>
        <span className="roster-count">{filtered.length} of {workers.length} workers</span>
      </div>

      <div className="table-scroll">
        <table className="roster-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} onClick={() => requestSort(c.key)} className="sortable-th">
                  {c.label}
                  {sortKey === c.key && <span className="sort-arrow">{direction === "asc" ? " ↑" : " ↓"}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((w) => (
              <tr key={w.worker_id} onClick={() => navigate(`/workers/${w.worker_id}`)} className="clickable-row">
                <td>
                  <div className="worker-cell">
                    <span className="avatar">{initials(w.name)}</span>
                    <div>
                      <div className="worker-name">{w.name}</div>
                      <div className="worker-sub">{w.phone} &middot; {w.language_pref.toUpperCase()}</div>
                    </div>
                  </div>
                </td>
                {showSubCentre && <td>{w.sub_centre_id || "—"}</td>}
                <td>{w.total_patients}</td>
                <td>{w.total_visits}</td>
                <td>{w.high_risk_count > 0 ? <span className="pill pill-high">{w.high_risk_count}</span> : 0}</td>
                <td>{w.medium_risk_count > 0 ? <span className="pill pill-medium">{w.medium_risk_count}</span> : 0}</td>
                <td>{w.pending_followups > 0 ? <span className="pill pill-pending">{w.pending_followups}</span> : 0}</td>
                <td>{w.last_visit_at ? new Date(w.last_visit_at).toLocaleDateString() : "Never"}</td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="empty-state">
                  No workers match this filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
