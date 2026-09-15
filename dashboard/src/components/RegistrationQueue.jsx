import { useCallback, useEffect, useState } from "react";
import { approveStaff, fetchRegistrations, rejectStaff } from "../api/client";
import { Empty, Section } from "./Surface";

function initials(name) {
  return name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}

/** Workers who registered in the app and cannot sign in until somebody
 *  here decides.
 *
 *  One component, shown on the ANM's overview and on the admin panel,
 *  because the two must never drift into disagreeing about what a
 *  registration looks like or what the buttons do. The backend scopes the
 *  list: an ANM sees the ASHAs who named her sub-centre, an admin sees
 *  everyone.
 *
 *  [collapseWhenEmpty] is how the ANM gets it. Her overview is a page
 *  about patients, and an empty "nobody is waiting" panel sitting above
 *  her escalations every day would be a permanent tax on the one screen
 *  that is supposed to surface urgent things. The admin panel keeps the
 *  empty state, because that page *is* the staff page and a section that
 *  vanishes there reads as broken.
 */
export default function RegistrationQueue({ collapseWhenEmpty = false, onChange }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [deciding, setDeciding] = useState(null);

  const load = useCallback(() => {
    fetchRegistrations()
      .then((data) => {
        setRows(data);
        setError(null);
      })
      .catch((err) => setError(err.response?.data?.detail || "Could not load registrations"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  // Approving is not paperwork -- it is the last step of her onboarding,
  // and every hour it sits here is an hour that worker cannot work.
  async function decide(worker, approve) {
    const reason = approve
      ? window.prompt(`Approve ${worker.name}? Add a note (optional) — e.g. who you rang to check.`) ?? ""
      : window.prompt(`Reject ${worker.name}? Give a reason (required, at least 5 characters).`);
    if (!approve && (!reason || reason.trim().length < 5)) return;

    setDeciding(worker.worker_id);
    setError(null);
    try {
      if (approve) {
        await approveStaff(worker.worker_id, reason.trim() || null);
      } else {
        await rejectStaff(worker.worker_id, reason.trim());
      }
      load();
      onChange?.();
    } catch (err) {
      setError(err.response?.data?.detail || "Could not save that decision");
    } finally {
      setDeciding(null);
    }
  }

  if (collapseWhenEmpty && !loading && rows.length === 0 && !error) return null;

  return (
    <Section
      title="Waiting for approval"
      sub="Workers who registered in the app. None of them can sign in until you decide. Ring the number before you approve — the system cannot check that she is who she says she is, only record that you did."
      aside={rows.length > 0 ? <span className="chip">{rows.length} waiting</span> : null}
    >
      {error && <p className="error">{error}</p>}
      {loading ? (
        <Empty>Loading registrations…</Empty>
      ) : rows.length === 0 ? (
        <Empty>Nobody is waiting. New registrations from the app appear here.</Empty>
      ) : (
        <div className="table-wrap">
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Role</th>
                  <th>Phone</th>
                  <th>Sub-centre</th>
                  <th>Registered</th>
                  <th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.worker_id}>
                    <td>
                      <div className="cell-with-avatar">
                        <span className="avatar">{initials(s.name)}</span>
                        <span className="cell-strong">{s.name}</span>
                      </div>
                    </td>
                    <td>
                      <span className="chip">{s.role.toUpperCase()}</span>
                    </td>
                    <td>
                      {/* The check itself is a phone call, so the number is
                          the one thing on the row that has to be one tap. */}
                      <a href={`tel:${s.phone}`}>{s.phone}</a>
                    </td>
                    <td>{s.sub_centre_id || <span className="muted">—</span>}</td>
                    <td className="muted">{new Date(s.created_at).toLocaleDateString()}</td>
                    <td>
                      <button
                        className="btn-quiet"
                        disabled={deciding === s.worker_id}
                        onClick={() => decide(s, true)}
                      >
                        Approve
                      </button>
                      <button
                        className="btn-quiet"
                        disabled={deciding === s.worker_id}
                        onClick={() => decide(s, false)}
                      >
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Section>
  );
}
