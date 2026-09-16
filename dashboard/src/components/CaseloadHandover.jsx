import { useEffect, useMemo, useState } from "react";
import { fetchWorkers, reassignCaseload } from "../api/client";
import { Section } from "./Surface";

/** Hand a whole caseload to another ASHA. Permanent.
 *
 * This is the one that needs a supervisor, and it is not the same thing
 * as the leave cover an ASHA arranges for herself. Cover lends sight of
 * the patients for a stated fortnight and lapses on its own; this moves
 * ownership and does not come back. An ASHA who could do it would be an
 * ASHA who could quietly empty her own list.
 *
 * Kept closed behind a button rather than sitting open on the page. It
 * is rare, it is irreversible from this screen, and a live dropdown of
 * every colleague's name under a worker's visit history is an invitation
 * to a mis-click that moves forty women to the wrong person.
 *
 * The reason is mandatory and that is the point of the whole control.
 * "She left the post", "maternity leave", "transferred to Khed" are
 * different facts about a real person's employment, and six months later
 * the audit log is the only place anybody can find out which happened.
 */
export default function CaseloadHandover({ worker, onDone }) {
  const [open, setOpen] = useState(false);
  const [colleagues, setColleagues] = useState([]);
  const [toWorkerId, setToWorkerId] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (!open) return;
    fetchWorkers()
      .then(setColleagues)
      .catch((err) => setError(err.response?.data?.detail || "Could not load the roster"));
  }, [open]);

  const options = useMemo(
    () => colleagues.filter((c) => c.worker_id !== worker.worker_id),
    [colleagues, worker.worker_id],
  );

  async function submit(e) {
    e.preventDefault();
    if (!toWorkerId || reason.trim().length < 5) {
      setError("Choose a worker and write a reason of at least five characters.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await reassignCaseload(worker.worker_id, toWorkerId, reason.trim());
      setResult(res);
      setOpen(false);
      setReason("");
      setToWorkerId("");
      onDone?.();
    } catch (err) {
      setError(err.response?.data?.detail || "Could not move the caseload");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      title="Caseload"
      sub="Moving a caseload is permanent and the patients do not come back on their own. For somebody who is only away for a while, she can set cover herself in the app — that lapses by itself and leaves ownership alone."
      aside={
        !open && (
          <button className="btn-quiet" onClick={() => setOpen(true)}>
            Hand over caseload
          </button>
        )
      }
    >
      {result && (
        <p className="muted">
          Moved {result.moved} {result.moved === 1 ? "patient" : "patients"} to{" "}
          {result.to_worker_name}. It is in the audit log.
        </p>
      )}

      {!open && !result && (
        <p className="muted">
          {worker.total_patients} {worker.total_patients === 1 ? "patient" : "patients"} are
          assigned to {worker.name}.
        </p>
      )}

      {open && (
        <form className="stack-form" onSubmit={submit}>
          <label>
            <span>Hand all {worker.total_patients} patients to</span>
            <select value={toWorkerId} onChange={(e) => setToWorkerId(e.target.value)}>
              <option value="">Choose a worker…</option>
              {options.map((c) => (
                <option key={c.worker_id} value={c.worker_id}>
                  {c.name}
                  {c.worker_code ? ` · ${c.worker_code}` : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Why (kept in the audit trail)</span>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Left the post, replaced by Kavita from 1 April"
            />
          </label>
          {error && <p className="error">{error}</p>}
          <div className="form-actions">
            <button className="btn-quiet" type="button" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="submit" disabled={saving}>
              {saving ? "Moving…" : "Move caseload"}
            </button>
          </div>
        </form>
      )}
    </Section>
  );
}
