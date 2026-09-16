import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CountTag, Empty, RiskTag } from "./Surface";

/** FR-08 accountability: which ASHA owes which patient a visit, and which
 * of those are already late.
 *
 * The follow-up split above this gives three totals -- done, pending,
 * overdue -- which tells a supervisor something is wrong but not whose
 * name to call. This is the row-level answer: the worker, the patient,
 * and how far past the deadline Agent 3 set for her risk level.
 *
 * Workers with nothing outstanding are listed too, marked "All clear".
 * An absent row would be ambiguous -- no work, or no data? -- and
 * "everyone else is fine" is half of what a supervisor is checking.
 *
 * Severity is carried by colour *and* wording ("3d overdue"), never by
 * colour alone: this gets read on a projector, and by people with
 * colour-vision deficiency. */
export default function FollowupCompliance({ compliance, showSubCentre }) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(() => new Set());

  if (!compliance) return <Empty>Loading visit accountability…</Empty>;

  const { workers = [], total_overdue = 0 } = compliance;
  if (workers.length === 0) {
    return <Empty>No ASHA workers in your scope yet.</Empty>;
  }

  const toggle = (workerId) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(workerId)) next.delete(workerId);
      else next.add(workerId);
      return next;
    });

  // Every worker starts closed.
  //
  // This used to open the overdue ones automatically, on the reasoning
  // that a supervisor should see the names without clicking. In practice
  // the page loaded as six stacked tables and eighty rows, and the one
  // thing this section is for -- reading down a short list of names and
  // their counts -- was buried under its own detail. The counts on each
  // header already say who needs chasing; the table is what you open
  // once you have decided whose to look at.
  const isOpen = (w) => expanded.has(w.worker_id);

  // Behind first, then by how far behind. Who needs chasing is the point
  // of the section, so it belongs at the top rather than somewhere you
  // scroll to find.
  const ordered = [...workers].sort(
    (a, b) =>
      b.overdue - a.overdue || b.due_today - a.due_today || a.worker_name.localeCompare(b.worker_name),
  );

  return (
    <>
      {total_overdue === 0 && (
        <p className="notice">Every scheduled follow-up is on time. Nothing needs chasing right now.</p>
      )}

      <div className="status-list">
        {ordered.map((w) => {
          const open = isOpen(w);
          const clear = w.overdue === 0 && w.due_today === 0 && w.upcoming === 0;
          return (
            <div key={w.worker_id} className="compliance-worker">
              <button
                type="button"
                className="compliance-head"
                onClick={() => toggle(w.worker_id)}
                aria-expanded={open}
              >
                <span className={open ? "caret is-open" : "caret"} aria-hidden="true">
                  ▸
                </span>
                <span className="compliance-name">{w.worker_name}</span>
                {showSubCentre && w.sub_centre_id && <span className="chip">{w.sub_centre_id}</span>}
                <span className="compliance-counts">
                  {clear ? (
                    <CountTag tone="clear">All clear</CountTag>
                  ) : (
                    <>
                      {w.overdue > 0 && <CountTag tone="high">{w.overdue} overdue</CountTag>}
                      {w.due_today > 0 && <CountTag tone="medium">{w.due_today} today</CountTag>}
                      {w.upcoming > 0 && <CountTag tone="muted">{w.upcoming} upcoming</CountTag>}
                    </>
                  )}
                </span>
              </button>

              {/* Always mounted, revealed by animating the grid row from
                  0fr to 1fr. A height transition needs two known heights,
                  and the height of a table nobody has measured is not one
                  of them -- which is why the usual version of this does a
                  JS measure on every toggle. The grid trick animates to
                  the real content height with no measuring, and without a
                  guessed max-height that clips a worker with thirty
                  overdue visits. The rows do exist while collapsed, so
                  the wrapper is inert rather than merely invisible. */}
              <div className="compliance-detail-wrap" data-open={open} inert={!open}>
               <div className="compliance-detail-inner">
              {!clear && (
                <div className="compliance-detail">
                  <div className="table-scroll">
                    <table className="data">
                      <thead>
                        <tr>
                          <th className="rail-cell" aria-label="Status" />
                          <th>Patient</th>
                          <th>Village</th>
                          <th>Risk</th>
                          <th>Due</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {w.visits.map((v) => (
                          <tr
                            key={v.action_id}
                            className="is-clickable"
                            onClick={() => navigate(`/patients/${v.patient_id}`)}
                          >
                            <td className={`rail-cell tone-${railTone(v.bucket)}`} />
                            <td>
                              <span className="cell-stack">
                                <span className="cell-strong">{v.patient_name}</span>
                                {/* The row is one doorstep; say when there
                                    is more than one reason to knock. */}
                                {v.also_pending > 0 && (
                                  <span className="cell-sub">
                                    +{v.also_pending} more follow-up
                                    {v.also_pending > 1 ? "s" : ""} at this visit
                                  </span>
                                )}
                              </span>
                            </td>
                            <td className="muted">{v.village || "—"}</td>
                            <td>
                              <RiskTag level={v.risk_level} />
                            </td>
                            <td className="muted">
                              {v.due_at ? new Date(v.due_at).toLocaleDateString() : "—"}
                            </td>
                            <td className={statusClass(v.bucket)}>{v.label}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {clear && (
                <div className="compliance-detail">
                  <p className="compliance-clear">No follow-up visits outstanding for {w.worker_name}.</p>
                </div>
              )}
               </div>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

function railTone(bucket) {
  if (bucket === "overdue") return "high";
  if (bucket === "due_today") return "medium";
  return "low";
}

function statusClass(bucket) {
  if (bucket === "overdue") return "risk-tag tone-high";
  if (bucket === "due_today") return "risk-tag tone-medium";
  return "muted";
}
