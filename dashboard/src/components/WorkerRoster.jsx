import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useSortableData } from "../hooks/useSortableData";
import { Empty } from "./Surface";

/** FR-08 "worker performance metrics": sortable, filterable roster --
 * clicking a worker drills into their full history (WorkerDetailPage).
 *
 * Counts are plain figures, not coloured chips. A table where every row
 * carries three filled pills is a table you cannot read: colour stops
 * meaning "look here" once everything has it. So zero renders as a muted
 * figure, a non-zero HIGH count takes the risk colour, and the row's
 * leading rail carries the worker's worst outstanding state -- letting a
 * supervisor scan the left edge and find who needs her without reading a
 * single number. */

const COLUMNS = [
  { key: "name", label: "Worker" },
  { key: "sub_centre_id", label: "Sub-centre", bmoOnly: true },
  { key: "total_patients", label: "Patients", numeric: true },
  { key: "total_visits", label: "Visits", numeric: true },
  { key: "high_risk_count", label: "High", numeric: true },
  { key: "medium_risk_count", label: "Medium", numeric: true },
  { key: "pending_followups", label: "Pending", numeric: true },
  { key: "last_visit_at", label: "Last visit" },
];

function initials(name) {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

/** The worst thing outstanding against this worker, which is what the
 * rail shows. Never green: a worker who is all clear needs no attention,
 * so her row stays quiet. */
function workerTone(w) {
  if (w.high_risk_count > 0) return "high";
  if (w.pending_followups > 0 || w.medium_risk_count > 0) return "medium";
  if (w.total_visits === 0) return "none";
  return "low";
}

/** Zero is information, but it isn't news -- render it quietly so the
 * non-zero counts are what the eye lands on. */
function Count({ value, tone }) {
  if (!value) return <span className="muted">0</span>;
  return <span className={`risk-tag tone-${tone}`}>{value}</span>;
}

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
    <>
      <div className="filters">
        <input
          className="grow"
          placeholder="Search worker name"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}>
          <option value="all">All workers</option>
          <option value="high">Has HIGH risk cases</option>
          <option value="pending">Has pending follow-ups</option>
          <option value="inactive">No visits logged yet</option>
        </select>
        <span className="result-count">
          {filtered.length} of {workers.length} workers
        </span>
      </div>

      {sorted.length === 0 ? (
        <Empty>No workers match this filter. Clear the search to see the full roster.</Empty>
      ) : (
        <div className="table-wrap">
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th className="rail-cell" aria-label="Status" />
                  {columns.map((c) => (
                    <th
                      key={c.key}
                      onClick={() => requestSort(c.key)}
                      className={c.numeric ? "sortable-th n" : "sortable-th"}
                    >
                      {c.label}
                      {sortKey === c.key && (
                        <span className="sort-arrow">{direction === "asc" ? " ↑" : " ↓"}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((w) => (
                  <tr
                    key={w.worker_id}
                    onClick={() => navigate(`/workers/${w.worker_id}`)}
                    className="is-clickable"
                  >
                    <td className={`rail-cell tone-${workerTone(w)}`} />
                    <td>
                      <div className="cell-with-avatar">
                        <span className="avatar">{initials(w.name)}</span>
                        <span className="cell-stack">
                          <span className="cell-strong">{w.name}</span>
                          <span className="cell-sub">
                            {w.phone} · {w.language_pref.toUpperCase()}
                          </span>
                        </span>
                      </div>
                    </td>
                    {showSubCentre && <td>{w.sub_centre_id || <span className="muted">—</span>}</td>}
                    <td className="n">{w.total_patients}</td>
                    <td className="n">{w.total_visits}</td>
                    <td className="n">
                      <Count value={w.high_risk_count} tone="high" />
                    </td>
                    <td className="n">
                      <Count value={w.medium_risk_count} tone="medium" />
                    </td>
                    <td className="n">
                      <Count value={w.pending_followups} tone="medium" />
                    </td>
                    <td>
                      {w.last_visit_at ? (
                        new Date(w.last_visit_at).toLocaleDateString()
                      ) : (
                        <span className="muted">Never</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
