import { useCallback, useEffect, useState } from "react";
import { createStaff, fetchAuditLog, fetchStaff } from "../api/client";
import RegistrationQueue from "../components/RegistrationQueue";
import { useSortableData } from "../hooks/useSortableData";
import AppShell from "../components/AppShell";
import { Empty, Section } from "../components/Surface";

const ROLE_LABELS = { asha: "ASHA", anm: "ANM", bmo: "BMO", admin: "Admin" };

const ACTION_TYPES = [
  "auth.login",
  "auth.login_failed",
  "visit.create",
  "risk.override",
  "patient.view",
  "patient.directory_view",
  "worker.view",
  "staff.create",
  "staff.registration_approved",
  "staff.registration_rejected",
  "auth.register",
  "auth.change_pin",
];

const EMPTY_FORM = { name: "", phone: "", pin: "", role: "asha", sub_centre_id: "", language_pref: "hi" };

function initials(name) {
  return name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}

/** NFR-SC1/SC4 + a fourth RBAC role (admin) that had nowhere to go: staff
 * management across all four roles (asha/anm/bmo/admin -- the ASHA-only
 * roster on the main dashboard can't show this) and a viewer over the
 * audit trail every sensitive read/write now writes to. Admin-only route.
 *
 * Two audit actions get the indigo rail: a risk override and a failed
 * login. Everything else here is routine and stays quiet -- which is the
 * only reason the two that aren't are findable in a list this long. */
export default function AdminPage() {
  const [staff, setStaff] = useState([]);
  const [staffLoading, setStaffLoading] = useState(true);
  const [staffError, setStaffError] = useState(null);

  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState(null);
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const [audit, setAudit] = useState([]);
  const [auditLoading, setAuditLoading] = useState(true);
  const [auditError, setAuditError] = useState(null);
  const [actionFilter, setActionFilter] = useState("all");
  const [actorSearch, setActorSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const loadStaff = useCallback(() => {
    setStaffLoading(true);
    fetchStaff()
      .then((data) => {
        setStaff(data);
        setStaffError(null);
      })
      .catch((err) => setStaffError(err.response?.data?.detail || "Failed to load staff"))
      .finally(() => setStaffLoading(false));
  }, []);

  const loadAudit = useCallback(() => {
    setAuditLoading(true);
    fetchAuditLog({
      actionType: actionFilter === "all" ? undefined : actionFilter,
      actorSearch: actorSearch || undefined,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo ? `${dateTo}T23:59:59` : undefined,
    })
      .then((data) => {
        setAudit(data);
        setAuditError(null);
      })
      .catch((err) => setAuditError(err.response?.data?.detail || "Failed to load audit log"))
      .finally(() => setAuditLoading(false));
  }, [actionFilter, actorSearch, dateFrom, dateTo]);

  useEffect(() => {
    loadStaff();
  }, [loadStaff]);

  useEffect(() => {
    loadAudit();
  }, [loadAudit]);

  async function handleCreateStaff(e) {
    e.preventDefault();
    setFormSubmitting(true);
    setFormError(null);
    try {
      await createStaff({ ...form, sub_centre_id: form.sub_centre_id.trim() || null });
      setForm(EMPTY_FORM);
      setShowForm(false);
      loadStaff();
    } catch (err) {
      setFormError(err.response?.data?.detail || "Failed to create account");
    } finally {
      setFormSubmitting(false);
    }
  }

  const {
    sorted: sortedStaff,
    sortKey: staffSortKey,
    direction: staffDirection,
    requestSort: requestStaffSort,
  } = useSortableData(staff, "role", "asc");

  return (
    <AppShell
      title="Administration"
      scope="Full district access"
      meta="Staff accounts and the audit trail of who accessed or changed what"
    >
      {staffError && <p className="error">{staffError}</p>}

      <RegistrationQueue onChange={loadStaff} />

      <Section
        title="Staff directory"
        sub="Every account across all four roles, including the supervisors the ASHA roster can't show."
        aside={
          <button className="btn-quiet" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "New account"}
          </button>
        }
      >
        {showForm && (
          <form className="panel-form" onSubmit={handleCreateStaff}>
            <div className="form-grid">
              <label>
                Name
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </label>
              <label>
                Phone
                <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} required />
              </label>
              <label>
                PIN (4–6 digits)
                <input value={form.pin} onChange={(e) => setForm({ ...form, pin: e.target.value })} required />
              </label>
              <label>
                Role
                <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  <option value="asha">ASHA</option>
                  <option value="anm">ANM</option>
                  <option value="bmo">BMO</option>
                  <option value="admin">Admin</option>
                </select>
              </label>
              <label>
                Sub-centre ID (optional)
                <input
                  value={form.sub_centre_id}
                  onChange={(e) => setForm({ ...form, sub_centre_id: e.target.value })}
                  placeholder="e.g. SC-PUNE-01"
                />
              </label>
              <label>
                Language
                <select
                  value={form.language_pref}
                  onChange={(e) => setForm({ ...form, language_pref: e.target.value })}
                >
                  <option value="hi">Hindi</option>
                  <option value="mr">Marathi</option>
                  <option value="ta">Tamil</option>
                  <option value="te">Telugu</option>
                  <option value="bn">Bengali</option>
                </select>
              </label>
            </div>
            {formError && <p className="error">{formError}</p>}
            <div className="override-actions">
              <button type="submit" disabled={formSubmitting}>
                {formSubmitting ? "Creating…" : "Create account"}
              </button>
            </div>
          </form>
        )}

        {staffLoading ? (
          <Empty>Loading staff accounts…</Empty>
        ) : sortedStaff.length === 0 ? (
          <Empty>No staff accounts yet. Use “New account” above to add the first one.</Empty>
        ) : (
          <div className="table-wrap">
            <div className="table-scroll">
              <table className="data">
                <thead>
                  <tr>
                    {[
                      { key: "name", label: "Name" },
                      { key: "role", label: "Role" },
                      { key: "phone", label: "Phone" },
                      { key: "sub_centre_id", label: "Sub-centre" },
                      { key: "language_pref", label: "Language" },
                      { key: "status", label: "Status" },
                      { key: "created_at", label: "Created" },
                    ].map((c) => (
                      <th key={c.key} onClick={() => requestStaffSort(c.key)} className="sortable-th">
                        {c.label}
                        {staffSortKey === c.key && (
                          <span className="sort-arrow">{staffDirection === "asc" ? " ↑" : " ↓"}</span>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sortedStaff.map((s) => (
                    <tr key={s.worker_id}>
                      <td>
                        <div className="cell-with-avatar">
                          <span className="avatar">{initials(s.name)}</span>
                          <span className="cell-strong">{s.name}</span>
                        </div>
                      </td>
                      <td>
                        <span className="chip">{ROLE_LABELS[s.role] || s.role}</span>
                      </td>
                      <td>{s.phone}</td>
                      <td>{s.sub_centre_id || <span className="muted">—</span>}</td>
                      <td>{s.language_pref?.toUpperCase()}</td>
                      <td>
                        {s.status === "active" ? (
                          <span className="muted">
                            Active
                            {s.approved_by_name ? ` \u00b7 by ${s.approved_by_name}` : ""}
                          </span>
                        ) : (
                          <span className="chip">{s.status === "pending" ? "Waiting" : "Rejected"}</span>
                        )}
                      </td>
                      <td className="muted">{new Date(s.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Section>

      <Section
        title="Audit trail"
        sub="Every login, override and sensitive read the backend has logged (NFR-SC4)."
        aside={<span className="chip">{audit.length} entries</span>}
      >
        {auditError && <p className="error">{auditError}</p>}

        <div className="filters">
          <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
            <option value="all">All actions</option>
            {ACTION_TYPES.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          <input
            className="grow"
            placeholder="Search actor name"
            value={actorSearch}
            onChange={(e) => setActorSearch(e.target.value)}
          />
          <label className="filter-label">
            From
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            to
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
        </div>

        {auditLoading ? (
          <Empty>Loading audit entries…</Empty>
        ) : audit.length === 0 ? (
          <Empty>No audit entries match this filter. Widen the date range or clear the action type.</Empty>
        ) : (
          <div className="table-wrap">
            <div className="table-scroll">
              <table className="data">
                <thead>
                  <tr>
                    <th className="rail-cell" aria-label="Kind" />
                    <th>Time</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Record</th>
                    <th>IP</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.map((a) => (
                    <tr key={a.log_id}>
                      <td className={`rail-cell tone-${auditTone(a.action_type)}`} />
                      <td className="muted">{new Date(a.timestamp).toLocaleString()}</td>
                      <td>
                        {a.actor_name ? (
                          <span className="cell-stack">
                            <span className="cell-strong">{a.actor_name}</span>
                            <span className="cell-sub">{ROLE_LABELS[a.actor_role] || a.actor_role}</span>
                          </span>
                        ) : (
                          <span className="muted">{a.user_id}</span>
                        )}
                      </td>
                      <td>{a.action_type}</td>
                      <td className="muted">
                        {a.record_type ? `${a.record_type}:${(a.record_id || "").slice(0, 8)}` : "—"}
                      </td>
                      <td className="muted">{a.ip_address || "—"}</td>
                      <td className="drivers">
                        {a.details ? (
                          <span className="cell-sub">{JSON.stringify(a.details)}</span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
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

/** A failed login is a security event; a risk override is a human
 * overruling the model. Those two are what an auditor is scanning for,
 * so they get a rail. Routine reads do not -- a list where every row is
 * marked is a list with nothing marked. */
function auditTone(actionType) {
  if (actionType === "auth.login_failed") return "high";
  if (actionType === "risk.override") return "human";
  return "none";
}
