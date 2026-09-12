import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchPatientHistory, overrideRisk } from "../api/client";
import { useAuth } from "../context/AuthContext";
import AppShell from "../components/AppShell";
import { Empty, RiskTag, Section } from "../components/Surface";

const RISK_LEVELS = ["HIGH", "MEDIUM", "LOW"];

/** One patient: who she is, then everything that has happened to her.
 *
 * The registration record comes before the timeline for the same reason
 * it does on the phone -- the baseline readings are what today's numbers
 * get compared against, and the phone number is what you use when the
 * visit didn't happen. Empty fields are shown as "not recorded" rather
 * than hidden: a blank blood pressure is information, and hiding the row
 * makes the record look complete when it isn't.
 *
 * Anything indigo on this page was decided by a person, not the model.
 * That is the one accent in the system and it is never used for
 * decoration, so a supervisor can tell AI output from human judgment
 * without a legend. */
export default function PatientDetailPage() {
  const { patientId } = useParams();
  const navigate = useNavigate();
  const { auth } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);

  // FR-03.3: an ANM (her own sub-centre) or a BMO (district-wide) can
  // correct a risk call from here -- an ASHA does the equivalent from the
  // mobile app, since this dashboard has no ASHA login. The backend
  // enforces the same roles (and Admin gets a 403 if they somehow try);
  // this just avoids showing a control that would only ever fail.
  const canOverride = auth?.role === "anm" || auth?.role === "bmo";
  const [overridingVisitId, setOverridingVisitId] = useState(null);
  const [overrideLevel, setOverrideLevel] = useState("MEDIUM");
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideError, setOverrideError] = useState(null);
  const [overrideSubmitting, setOverrideSubmitting] = useState(false);

  useEffect(() => {
    fetchPatientHistory(patientId)
      .then(setData)
      .catch((err) => setError(err.response?.data?.detail || "Failed to load patient"));
  }, [patientId]);

  function startOverride(e, visit) {
    e.stopPropagation();
    setOverridingVisitId(visit.visit_id);
    setOverrideLevel(RISK_LEVELS.find((l) => l !== visit.risk_level) || "MEDIUM");
    setOverrideReason("");
    setOverrideError(null);
  }

  function cancelOverride(e) {
    e.stopPropagation();
    setOverridingVisitId(null);
    setOverrideError(null);
  }

  async function submitOverride(e, visitId) {
    e.stopPropagation();
    setOverrideSubmitting(true);
    setOverrideError(null);
    try {
      const result = await overrideRisk(visitId, overrideLevel, overrideReason);
      setData((prev) => ({
        ...prev,
        visits: prev.visits.map((v) =>
          v.visit_id === visitId
            ? {
                ...v,
                risk_level: result.new_risk_level,
                risk_overridden: true,
                risk_override_reason: result.reason,
                overridden_by_name: result.overridden_by_name,
                overridden_by_role: result.overridden_by_role,
              }
            : v,
        ),
      }));
      setOverridingVisitId(null);
    } catch (err) {
      setOverrideError(err.response?.data?.detail || "Could not save the override.");
    } finally {
      setOverrideSubmitting(false);
    }
  }

  if (error) {
    return (
      <AppShell title="Patient">
        <button className="btn-quiet" style={{ alignSelf: "flex-start" }} onClick={() => navigate(-1)}>
          ← Back
        </button>
        <p className="error">{error}</p>
      </AppShell>
    );
  }
  if (!data) {
    return (
      <AppShell title="Patient" meta="Loading…">
        <Empty>Loading patient record…</Empty>
      </AppShell>
    );
  }

  const initials = data.patient_name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const summary = [
    data.age ? `${data.age} years` : null,
    data.village,
    data.pregnancy_stage ? `${data.pregnancy_stage} pregnant` : null,
  ]
    .filter(Boolean)
    .join("  ·  ");

  const latest = data.visits[0];

  return (
    <AppShell
      title={data.patient_name}
      meta={summary || "No details recorded"}
      actions={
        <button className="btn-quiet" onClick={() => navigate(-1)}>
          ← Back
        </button>
      }
    >
      <div className="detail-id">
        <span className="avatar avatar-lg">{initials}</span>
        <div>
          <p className="cell-strong">
            {latest ? (
              <>
                Currently <RiskTag level={latest.risk_level} />
              </>
            ) : (
              "No visits recorded yet"
            )}
          </p>
          <p className="muted" style={{ fontSize: 13 }}>
            Registered to{" "}
            <button type="button" className="btn-bare" onClick={() => navigate(`/workers/${data.worker_id}`)}>
              {data.worker_name}
            </button>
          </p>
        </div>
      </div>

      <Section
        title="Registration record"
        sub="Taken once when she was registered. Readings from a visit go on the timeline below, where they set the risk level."
      >
        <div className="record">
          <Field label="Age" value={data.age} />
          <Field label="Gender" value={data.gender} capitalize />
          <Field label="Village" value={data.village} />
          <Field label="Phone" value={data.phone} />
          <Field label="Pregnancy stage" value={data.pregnancy_stage} />
          <Field
            label="Blood pressure"
            value={
              data.bp_systolic && data.bp_diastolic
                ? `${data.bp_systolic}/${data.bp_diastolic} mmHg`
                : null
            }
          />
          <Field label="Blood sugar (fasting)" value={fmtSugar(data.blood_sugar_fasting)} />
          <Field label="Blood sugar (random)" value={fmtSugar(data.blood_sugar_random)} />
          <Field
            label="Registered"
            value={data.registered_at ? new Date(data.registered_at).toLocaleDateString() : null}
          />
        </div>
      </Section>

      <Section title="Visit timeline" aside={<span className="chip">{data.visits.length} visits</span>}>
        {data.visits.length === 0 ? (
          <Empty>No visits recorded yet. They appear here as soon as her ASHA submits one from the app.</Empty>
        ) : (
          <div className="status-list">
            {data.visits.map((v) => {
              const isOpen = expanded === v.visit_id;
              const isOverriding = overridingVisitId === v.visit_id;
              return (
                <div key={v.visit_id} className={`visit tone-${(v.risk_level || "low").toLowerCase()}`}>
                  <span className="visit-rail" aria-hidden="true" />
                  <div className="visit-body">
                    <div
                      className="visit-head"
                      onClick={() => setExpanded(isOpen ? null : v.visit_id)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") setExpanded(isOpen ? null : v.visit_id);
                      }}
                    >
                      <span className="visit-when">{new Date(v.created_at).toLocaleString()}</span>
                      <RiskTag level={v.risk_level} />
                      {canOverride && !isOverriding && (
                        <button className="override-btn" onClick={(e) => startOverride(e, v)}>
                          Override risk
                        </button>
                      )}
                      {v.extracted && (
                        <span className="expand-hint">
                          {isOpen ? "Collapse" : "Full record"}
                        </span>
                      )}
                    </div>

                    {/* The transcript is in the language she spoke -- shown
                        as heard, never translated. Hind's Devanagari cut
                        is loaded so it sets properly. */}
                    {v.transcript && <p className="transcript">“{v.transcript}”</p>}

                    {v.risk_overridden && (
                      <div className="human-note">
                        <strong>
                          Corrected by {v.overridden_by_name || "a supervisor"}
                          {v.overridden_by_role ? ` (${v.overridden_by_role.toUpperCase()})` : ""}
                        </strong>
                        {v.risk_override_reason && <div className="muted">“{v.risk_override_reason}”</div>}
                      </div>
                    )}

                    {isOverriding && (
                      <div className="override-form" onClick={(e) => e.stopPropagation()}>
                        <label htmlFor={`level-${v.visit_id}`}>Correct risk level to</label>
                        <select
                          id={`level-${v.visit_id}`}
                          value={overrideLevel}
                          onChange={(e) => setOverrideLevel(e.target.value)}
                        >
                          {RISK_LEVELS.map((lvl) => (
                            <option key={lvl} value={lvl} disabled={lvl === v.risk_level}>
                              {lvl}
                              {lvl === v.risk_level ? " (current — no change)" : ""}
                            </option>
                          ))}
                        </select>
                        <label htmlFor={`reason-${v.visit_id}`}>Reason (required, kept in the audit trail)</label>
                        <textarea
                          id={`reason-${v.visit_id}`}
                          value={overrideReason}
                          onChange={(e) => setOverrideReason(e.target.value)}
                          placeholder="e.g. Called the patient directly, BP retest was normal — original reading was a faulty cuff."
                        />
                        {overrideError && <p className="error">{overrideError}</p>}
                        <div className="override-actions">
                          <button className="btn-quiet" onClick={cancelOverride} disabled={overrideSubmitting}>
                            Cancel
                          </button>
                          <button
                            className="btn-submit"
                            onClick={(e) => submitOverride(e, v.visit_id)}
                            disabled={overrideSubmitting || overrideReason.trim().length < 5}
                          >
                            {overrideSubmitting ? "Saving…" : "Save correction"}
                          </button>
                        </div>
                      </div>
                    )}

                    {isOpen && v.extracted && (
                      <dl className="extracted">
                        {Object.entries(v.extracted)
                          .filter(
                            ([k, val]) =>
                              k !== "confidence_scores" && val !== null && val !== undefined && val !== "",
                          )
                          .map(([k, val]) => (
                            <div key={k} className="extracted-row">
                              <dt>{k.replace(/_/g, " ")}</dt>
                              <dd>{Array.isArray(val) ? val.join(", ") || "—" : String(val)}</dd>
                            </div>
                          ))}
                      </dl>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Section>
    </AppShell>
  );
}

function fmtSugar(v) {
  return v ? `${v} mg/dL` : null;
}

/** A labelled row that renders the gap honestly when nothing was
 * recorded, rather than disappearing. */
function Field({ label, value, capitalize }) {
  const empty = value === null || value === undefined || value === "";
  return (
    <div className="record-row">
      <span className="record-label">{label}</span>
      <span
        className={empty ? "record-value is-empty" : "record-value"}
        style={capitalize && !empty ? { textTransform: "capitalize" } : undefined}
      >
        {empty ? "Not recorded" : value}
      </span>
    </div>
  );
}
