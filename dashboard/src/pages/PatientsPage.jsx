import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchAllPatients } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useSortableData } from "../hooks/useSortableData";
import AppShell from "../components/AppShell";
import { Empty, RiskTag } from "../components/Surface";

function initials(name) {
  return name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}

/** Why this patient is in today's work, in the fewest words that are still
 *  true. Hours below a day, days above it -- the HIGH follow-up window is
 *  only 48 hours long, so rounding six hours late down to "0 days" would
 *  report a missed emergency as fine. Returns "" for a HIGH that is not
 *  late: the severity tag beside it already says that, and repeating it
 *  would make the note something to skim past. */
function attentionNote(p) {
  if (p.attention_reason === "overdue") {
    return p.hours_overdue < 24
      ? `${p.hours_overdue}h overdue`
      : `${Math.floor(p.hours_overdue / 24)}d overdue`;
  }
  if (p.attention_reason === "due_today") return "Due today";
  return "";
}

/** FR-08 drill-down: "which patients are my ASHA workers actually treating
 * right now" -- every patient in scope (ANM's sub-centre, or BMO/Admin's
 * whole district), filterable by gender, risk level, and when they were
 * registered. The roster answers "who are my workers"; this answers "who
 * are their patients", which nothing else in the dashboard shows. */
export default function PatientsPage() {
  const navigate = useNavigate();
  const { auth } = useAuth();
  const isBmo = auth?.role === "bmo" || auth?.role === "admin";

  const [patients, setPatients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [search, setSearch] = useState("");
  const [genderFilter, setGenderFilter] = useState("all");
  const [riskFilter, setRiskFilter] = useState("all");
  const [registeredAfter, setRegisteredAfter] = useState("");
  const [registeredBefore, setRegisteredBefore] = useState("");

  useEffect(() => {
    fetchAllPatients()
      .then((data) => {
        setPatients(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.response?.data?.detail || "Failed to load patients");
        setLoading(false);
      });
  }, []);

  const filtered = useMemo(() => {
    return patients.filter((p) => {
      if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
      if (genderFilter !== "all" && (p.gender || "").toLowerCase() !== genderFilter) return false;
      if (riskFilter === "unrecorded" && p.risk_status) return false;
      if (riskFilter === "attention" && !p.needs_attention) return false;
      if (riskFilter !== "all" && riskFilter !== "unrecorded" && riskFilter !== "attention" && p.risk_status !== riskFilter)
        return false;
      if (registeredAfter && new Date(p.registered_at) < new Date(registeredAfter)) return false;
      if (registeredBefore && new Date(p.registered_at) > new Date(`${registeredBefore}T23:59:59`)) return false;
      return true;
    });
  }, [patients, search, genderFilter, riskFilter, registeredAfter, registeredBefore]);

  // null, not "registered_at": the list arrives from the server already in
  // triage order (backend/app/services/patient_priority.py), and the hook
  // passes items through untouched when it has no key. Every column header
  // still sorts on click -- this only changes what an ANM reads at 9am,
  // which "newest registration first" was answering a question nobody had
  // asked.
  const { sorted, sortKey, direction, requestSort } = useSortableData(filtered, null);

  const columns = [
    { key: "name", label: "Patient" },
    { key: "gender", label: "Gender" },
    { key: "age", label: "Age", numeric: true },
    { key: "village", label: "Village" },
    { key: "worker_name", label: "ASHA worker" },
    ...(isBmo ? [{ key: "sub_centre_id", label: "Sub-centre" }] : []),
    { key: "risk_status", label: "Risk" },
    { key: "total_visits", label: "Visits", numeric: true },
    { key: "registered_at", label: "Registered" },
  ];

  // "Needs attention" rather than "HIGH": a mother two days past her
  // follow-up is today's work even at MEDIUM, and a HIGH seen this morning
  // is not. Counting HIGH alone reported a severity where the page is
  // being asked about a workload.
  const attentionCount = patients.filter((p) => p.needs_attention).length;

  return (
    <AppShell
      title="Patients"
      scope={isBmo ? "District-wide — every sub-centre" : "Scoped to your sub-centre"}
      meta={
        loading
          ? "Loading…"
          : `${patients.length} registered${attentionCount ? ` \u00b7 ${attentionCount} need attention today` : ""}`
      }
    >
      {error && <p className="error">{error}</p>}

      <div className="filters">
        <input
          className="grow"
          placeholder="Search patient name"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={genderFilter} onChange={(e) => setGenderFilter(e.target.value)}>
          <option value="all">All genders</option>
          <option value="female">Female</option>
          <option value="male">Male</option>
          <option value="other">Other</option>
        </select>
        <select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}>
          <option value="all">All risk levels</option>
          <option value="HIGH">HIGH only</option>
          <option value="MEDIUM">MEDIUM only</option>
          <option value="LOW">LOW only</option>
          <option value="unrecorded">No visits yet</option>
          <option value="attention">Needs attention today</option>
        </select>
        <label className="filter-label">
          Registered
          <input type="date" value={registeredAfter} onChange={(e) => setRegisteredAfter(e.target.value)} />
          to
          <input type="date" value={registeredBefore} onChange={(e) => setRegisteredBefore(e.target.value)} />
        </label>
        <span className="result-count">
          {filtered.length} of {patients.length} patients
        </span>
      </div>

      {loading ? (
        <Empty>Loading patients…</Empty>
      ) : sorted.length === 0 ? (
        <Empty>No patients match these filters. Clear the search or widen the date range.</Empty>
      ) : (
        <div className="table-wrap">
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th className="rail-cell" aria-label="Risk" />
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
                {sorted.map((p) => (
                  <tr key={p.id} onClick={() => navigate(`/patients/${p.id}`)} className="is-clickable">
                    <td className={`rail-cell tone-${(p.risk_status || "none").toLowerCase()}`} />
                    <td>
                      <div className="cell-with-avatar">
                        <span className="avatar">{initials(p.name)}</span>
                        <span className="cell-strong">{p.name}</span>
                      </div>
                    </td>
                    <td style={{ textTransform: "capitalize" }}>
                      {p.gender || <span className="muted">—</span>}
                    </td>
                    <td className="n">{p.age ?? <span className="muted">—</span>}</td>
                    <td>{p.village || <span className="muted">—</span>}</td>
                    <td>
                      <button
                        type="button"
                        className="btn-bare"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/workers/${p.worker_id}`);
                        }}
                      >
                        {p.worker_name}
                      </button>
                    </td>
                    {isBmo && <td>{p.sub_centre_id || <span className="muted">—</span>}</td>}
                    <td>
                      {p.risk_status ? <RiskTag level={p.risk_status} /> : <span className="muted">No visits</span>}
                      {p.needs_attention && attentionNote(p) && (
                        <span
                          className={`attention-note${p.risk_status === "HIGH" ? "" : " tone-medium"}`}
                        >
                          {attentionNote(p)}
                        </span>
                      )}
                    </td>
                    <td className="n">{p.total_visits}</td>
                    <td>{new Date(p.registered_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </AppShell>
  );
}
