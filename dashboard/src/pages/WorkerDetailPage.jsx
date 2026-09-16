import { useCallback, useEffect, useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchWorkerHistory } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useSortableData } from "../hooks/useSortableData";
import AppShell from "../components/AppShell";
import StatStrip from "../components/StatStrip";
import CaseloadHandover from "../components/CaseloadHandover";
import { Empty, RiskTag, Section } from "../components/Surface";

/** One ASHA worker: her figures, then every visit she has recorded.
 *
 * The identity block carries her phone number and language because a
 * supervisor looking at this page is usually about to ring her -- and
 * which language she works in decides how that call goes. */
export default function WorkerDetailPage() {
  const { workerId } = useParams();
  const navigate = useNavigate();
  const { auth } = useAuth();
  // A BMO has read-only access to individual records (SRS table 4), so
  // she gets the figures and not the handover control.
  const canReassign = auth?.role === "anm" || auth?.role === "admin";
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [riskFilter, setRiskFilter] = useState("all");

  const load = useCallback(() => {
    fetchWorkerHistory(workerId)
      .then(setData)
      .catch((err) => setError(err.response?.data?.detail || "Failed to load worker"));
  }, [workerId]);

  useEffect(load, [load]);

  const visits = useMemo(() => {
    if (!data) return [];
    if (riskFilter === "all") return data.visits;
    return data.visits.filter((v) => v.risk_level === riskFilter);
  }, [data, riskFilter]);

  const { sorted, sortKey, direction, requestSort } = useSortableData(visits, "created_at", "desc");

  if (error) {
    return (
      <AppShell title="Worker">
        <button className="btn-bare back-link" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <p className="error">{error}</p>
      </AppShell>
    );
  }
  if (!data) {
    return (
      <AppShell title="Worker" meta="Loading…">
        <Empty>Loading worker history…</Empty>
      </AppShell>
    );
  }

  const w = data.worker;
  const initials = w.name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();

  const Th = ({ k, label }) => (
    <th onClick={() => requestSort(k)} className="sortable-th">
      {label}
      {sortKey === k && <span className="sort-arrow">{direction === "asc" ? " ↑" : " ↓"}</span>}
    </th>
  );

  return (
    <AppShell
      title={w.name}
      meta={[w.worker_code, w.phone, w.sub_centre_id || "No sub-centre", w.language_pref.toUpperCase()]
        .filter(Boolean)
        .join("  ·  ")}
      actions={
        <button className="btn-quiet" onClick={() => navigate(-1)}>
          ← Back
        </button>
      }
    >
      <div className="detail-id">
        <span className="avatar avatar-lg">{initials}</span>
        <div>
          <p className="cell-strong">ASHA worker</p>
          <p className="muted" style={{ fontSize: 13 }}>
            {w.last_visit_at
              ? `Last recorded a visit ${new Date(w.last_visit_at).toLocaleDateString()}`
              : "Has not recorded a visit yet"}
          </p>
        </div>
      </div>

      <StatStrip
        stats={[
          { label: "Patients treated", value: w.total_patients },
          { label: "Total visits", value: w.total_visits },
          {
            label: "HIGH risk flags",
            value: w.high_risk_count,
            tone: w.high_risk_count > 0 ? "high" : null,
          },
          {
            label: "Pending follow-ups",
            value: w.pending_followups,
            tone: w.pending_followups > 0 ? "medium" : null,
          },
        ]}
      />

      {canReassign && <CaseloadHandover worker={w} onDone={load} />}

      <Section
        title="Visit history"
        sub="Every visit this worker has recorded. Click a row for the patient's full timeline."
        aside={
          <select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}>
            <option value="all">All risk levels</option>
            <option value="HIGH">HIGH only</option>
            <option value="MEDIUM">MEDIUM only</option>
            <option value="LOW">LOW only</option>
          </select>
        }
      >
        {sorted.length === 0 ? (
          <Empty>
            {data.visits.length === 0
              ? "No visits recorded yet. They appear here as soon as she submits one from the app."
              : "No visits at this risk level."}
          </Empty>
        ) : (
          <div className="table-wrap">
            <div className="table-scroll">
              <table className="data">
                <thead>
                  <tr>
                    <th className="rail-cell" aria-label="Risk" />
                    <Th k="patient_name" label="Patient" />
                    <Th k="risk_level" label="Risk" />
                    <Th k="created_at" label="Recorded" />
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((v) => (
                    <tr
                      key={v.visit_id}
                      className="is-clickable"
                      onClick={() => navigate(`/patients/${v.patient_id}`)}
                    >
                      <td className={`rail-cell tone-${(v.risk_level || "none").toLowerCase()}`} />
                      <td className="cell-strong">{v.patient_name}</td>
                      <td>
                        <RiskTag level={v.risk_level} />
                      </td>
                      <td className="muted">{new Date(v.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Section>
    </AppShell>
  );
}
