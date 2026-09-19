import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSortableData } from "../hooks/useSortableData";
import { Empty } from "./Surface";

/** FR-06.2: unactioned HIGH risk cases -- enriched with patient/worker
 * context and the actual clinical drivers, not just a bare name.
 *
 * Every row here is HIGH by definition, so a risk column would be a
 * column of identical words. What varies, and what a supervisor triages
 * on, is *how long it has sat* -- so that is the emphasised figure, and
 * the row's rail goes full red once a case passes the 48-hour
 * escalation threshold. */
export default function EscalationList({ escalations, showSubCentre }) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(null);
  // Resolving a case (with its mandatory clinical-review note) is a
  // patient-profile-only action now -- see PatientDetailPage. This list
  // is read-only triage; a supervisor clicks the patient's name (below)
  // to go review and resolve there. The row drops off on its own once
  // DashboardPage's next poll re-fetches /escalations/pending and the
  // case is no longer unactioned -- no local "resolved" state to track.
  const { sorted, sortKey, direction, requestSort } = useSortableData(escalations, "hours_elapsed", "desc");

  if (escalations.length === 0) {
    return <Empty>No unactioned HIGH risk cases right now. Every flagged visit has been picked up.</Empty>;
  }

  const Th = ({ k, label, numeric }) => (
    <th onClick={() => requestSort(k)} className={numeric ? "sortable-th n" : "sortable-th"}>
      {label}
      {sortKey === k && <span className="sort-arrow">{direction === "asc" ? " ↑" : " ↓"}</span>}
    </th>
  );

  return (
    <div className="table-wrap">
      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th className="rail-cell" aria-label="Status" />
              <Th k="patient" label="Patient" />
              <Th k="worker" label="ASHA worker" />
              {showSubCentre && <Th k="worker_sub_centre" label="Sub-centre" />}
              <Th k="hours_elapsed" label="Waiting" numeric />
              <th>Why it was flagged</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((e) => {
              const isOpen = expanded === e.visit_id;
              const escalated = e.hours_elapsed >= 48;
              return (
                <tr
                  key={e.visit_id}
                  className="is-clickable"
                  onClick={() => setExpanded(isOpen ? null : e.visit_id)}
                >
                  <td className={escalated ? "rail-cell tone-high" : "rail-cell tone-medium"} />
                  <td>
                    <span className="cell-stack">
                      <button
                        type="button"
                        className="btn-bare cell-strong"
                        onClick={(ev) => {
                          ev.stopPropagation();
                          navigate(`/patients/${e.patient_id}`);
                        }}
                      >
                        {e.patient}
                      </button>
                      <span className="cell-sub">
                        {[e.patient_age ? `${e.patient_age} yrs` : null, e.patient_village]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </span>
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn-bare"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        navigate(`/workers/${e.worker_id}`);
                      }}
                    >
                      {e.worker}
                    </button>
                  </td>
                  {showSubCentre && <td>{e.worker_sub_centre || <span className="muted">—</span>}</td>}
                  <td className="n">
                    <span className={escalated ? "risk-tag tone-high" : undefined}>
                      {formatWait(e.hours_elapsed)}
                    </span>
                    {escalated && <div className="cell-sub">past 48h</div>}
                  </td>
                  <td className="drivers">
                    {isOpen ? (
                      e.drivers.length > 0 ? (
                        <>
                          <ul className="drivers-list">
                            {e.drivers.map((d, i) => (
                              <li key={i}>{d}</li>
                            ))}
                          </ul>
                          {/* The NHM sections the judgement was grounded on.
                              Absent for a flag the threshold engine raised on
                              its own, and for everything recorded before the
                              corpus existed -- so nothing is rendered rather
                              than a "no source" label, which would read as a
                              defect in the row instead of the ordinary case. */}
                          {e.citations?.length > 0 && (
                            <ul className="citation-list">
                              {e.citations.map((c, i) => (
                                <li key={i}>
                                  {c.url ? (
                                    <a href={c.url} target="_blank" rel="noreferrer">{c.label}</a>
                                  ) : (
                                    c.label
                                  )}
                                </li>
                              ))}
                            </ul>
                          )}
                        </>
                      ) : (
                        <span className="muted">No drivers recorded</span>
                      )
                    ) : (
                      <span className="cell-sub">
                        {e.drivers[0] || "—"}
                        {e.drivers.length > 1 && ` (+${e.drivers.length - 1} more)`}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Hours are the right unit for the first two days, which is the window
 * that matters here; past that "3d" is easier to judge at a glance than
 * "74.2h". */
function formatWait(hours) {
  if (hours < 48) return `${hours.toFixed(0)}h`;
  return `${Math.floor(hours / 24)}d`;
}
