import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSortableData } from "../hooks/useSortableData";

/** FR-06.2: unactioned HIGH risk cases -- enriched with patient/worker
 * context and the actual clinical drivers (not just a bare name), sortable
 * by any column. */
export default function EscalationList({ escalations, showSubCentre }) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(null);
  const { sorted, sortKey, direction, requestSort } = useSortableData(escalations, "hours_elapsed", "desc");

  if (escalations.length === 0) {
    return <p className="empty-state">No unactioned HIGH risk cases right now.</p>;
  }

  const Th = ({ k, label }) => (
    <th onClick={() => requestSort(k)} className="sortable-th">
      {label}
      {sortKey === k && <span className="sort-arrow">{direction === "asc" ? " ↑" : " ↓"}</span>}
    </th>
  );

  return (
    <div className="table-scroll">
      <table className="escalation-table">
        <thead>
          <tr>
            <Th k="patient" label="Patient" />
            <Th k="worker" label="ASHA Worker" />
            {showSubCentre && <Th k="worker_sub_centre" label="Sub-centre" />}
            <Th k="hours_elapsed" label="Time elapsed" />
            <th>Drivers</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((e) => {
            const isOpen = expanded === e.visit_id;
            return (
              <tr
                key={e.visit_id}
                className={`clickable-row ${e.hours_elapsed >= 48 ? "row-escalated" : ""}`}
                onClick={() => setExpanded(isOpen ? null : e.visit_id)}
              >
                <td>
                  <div className="patient-cell">
                    <span
                      className="link worker-name"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        navigate(`/patients/${e.patient_id}`);
                      }}
                    >
                      {e.patient}
                    </span>
                    <div className="worker-sub">
                      {e.patient_age ? `${e.patient_age}y` : ""} {e.patient_village ? `· ${e.patient_village}` : ""}
                    </div>
                  </div>
                </td>
                <td>
                  <span
                    className="link"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      navigate(`/workers/${e.worker_id}`);
                    }}
                  >
                    {e.worker}
                  </span>
                </td>
                {showSubCentre && <td>{e.worker_sub_centre || "—"}</td>}
                <td>
                  {e.hours_elapsed.toFixed(1)}h
                  {e.hours_elapsed >= 48 && <span className="badge-escalated">ESCALATED</span>}
                </td>
                <td className="drivers-cell">
                  {isOpen ? (
                    e.drivers.length > 0 ? (
                      <ul className="drivers-list">
                        {e.drivers.map((d, i) => (
                          <li key={i}>{d}</li>
                        ))}
                      </ul>
                    ) : (
                      <span className="empty-state">No drivers recorded</span>
                    )
                  ) : (
                    <span className="drivers-preview">
                      {e.drivers[0] || "—"} {e.drivers.length > 1 && `(+${e.drivers.length - 1} more, click to expand)`}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
