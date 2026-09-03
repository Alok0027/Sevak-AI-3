import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchPatientHistory } from "../api/client";

const RISK_COLOR = { HIGH: "#dc2626", MEDIUM: "#d97706", LOW: "#16a34a" };

export default function PatientDetailPage() {
  const { patientId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    fetchPatientHistory(patientId)
      .then(setData)
      .catch((err) => setError(err.response?.data?.detail || "Failed to load patient"));
  }, [patientId]);

  if (error) {
    return (
      <div className="dashboard-page">
        <button className="back-link" onClick={() => navigate(-1)}>&larr; Back</button>
        <p className="error">{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="dashboard-page">
        <p>Loading...</p>
      </div>
    );
  }

  return (
    <div className="dashboard-page">
      <button className="back-link" onClick={() => navigate(-1)}>&larr; Back</button>

      <div className="detail-header">
        <div className="avatar avatar-lg">
          {data.patient_name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase()}
        </div>
        <div>
          <h1>{data.patient_name}</h1>
          <p className="subtitle">
            {data.age ? `${data.age} years` : "Age unknown"} &middot; {data.village || "Village unknown"}
            {data.pregnancy_stage && ` · ${data.pregnancy_stage} pregnant`}
          </p>
          <p className="subtitle">
            ASHA worker: <span className="link" onClick={() => navigate(`/workers/${data.worker_id}`)}>{data.worker_name}</span>
          </p>
        </div>
      </div>

      <section className="panel">
        <h2>Visit Timeline ({data.visits.length})</h2>
        {data.visits.length === 0 && <p className="empty-state">No visits recorded yet.</p>}
        <div className="timeline">
          {data.visits.map((v) => {
            const isOpen = expanded === v.visit_id;
            return (
              <div key={v.visit_id} className="timeline-entry" onClick={() => setExpanded(isOpen ? null : v.visit_id)}>
                <div className="timeline-dot" style={{ background: RISK_COLOR[v.risk_level] || "#888" }} />
                <div className="timeline-body">
                  <div className="timeline-header">
                    <strong>{new Date(v.created_at).toLocaleString()}</strong>
                    <span className="pill" style={{ background: RISK_COLOR[v.risk_level] || "#888" }}>
                      {v.risk_level || "Unrecorded"}
                    </span>
                  </div>
                  {v.transcript && <p className="transcript">"{v.transcript}"</p>}
                  {isOpen && v.extracted && (
                    <dl className="extracted-fields">
                      {Object.entries(v.extracted)
                        .filter(([k, val]) => k !== "confidence_scores" && val !== null && val !== undefined && val !== "")
                        .map(([k, val]) => (
                          <div key={k} className="extracted-row">
                            <dt>{k.replace(/_/g, " ")}</dt>
                            <dd>{Array.isArray(val) ? val.join(", ") || "—" : String(val)}</dd>
                          </div>
                        ))}
                    </dl>
                  )}
                  <span className="expand-hint">{isOpen ? "Click to collapse" : "Click to see extracted record"}</span>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
