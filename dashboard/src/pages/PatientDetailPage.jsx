import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchPatientHistory, overrideRisk, resolveRisk } from "../api/client";
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
// The readings worth seeing at a glance on a timeline row. Deliberately
// short: the full extracted record is one click away behind "Full record",
// and a timeline that prints every field stops being scannable.
function summariseReadings(extracted) {
  if (!extracted) return "";
  const parts = [];
  if (extracted.bp_systolic && extracted.bp_diastolic) {
    parts.push(`BP ${extracted.bp_systolic}/${extracted.bp_diastolic}`);
  }
  if (extracted.temperature_c) parts.push(`${extracted.temperature_c}\u00B0C`);
  if (extracted.blood_sugar_random) parts.push(`Sugar ${extracted.blood_sugar_random} mg/dL`);
  if (extracted.blood_sugar_fasting) parts.push(`Fasting ${extracted.blood_sugar_fasting} mg/dL`);
  if (extracted.weight_kg) parts.push(`${extracted.weight_kg} kg`);
  if (extracted.medication_compliance === "non_compliant") parts.push("medication missed");
  return parts.join(" \u00B7 ");
}

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

  // Resolving an open HIGH case with a mandatory clinical-review note --
  // same anm/bmo roles as override, but a separate action: it does not
  // relabel the visit, it just closes the case out (see resolve-risk on
  // the backend). Lives ONLY here, on the patient's own record -- the
  // Overview escalation table is read-only triage and has no path into
  // this, by design (see EscalationList).
  // Resolution is a fact about the patient, not about one row in her
  // timeline -- so this is a single flag, not a visit id.
  const [resolving, setResolving] = useState(false);
  const [resolveNote, setResolveNote] = useState("");
  const [resolveError, setResolveError] = useState(null);
  const [resolveSubmitting, setResolveSubmitting] = useState(false);

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
    setResolving(false);
  }

  function startResolve() {
    setResolving(true);
    setResolveNote("");
    setResolveError(null);
    setOverridingVisitId(null);
  }

  function cancelResolve() {
    setResolving(false);
    setResolveError(null);
  }

  async function submitResolve(openHighVisits) {
    setResolveSubmitting(true);
    setResolveError(null);
    const note = resolveNote.trim();
    try {
      // Every HIGH visit she still has open, closed under one review.
      //
      // The API resolves one visit at a time, which is right -- each flag
      // is its own record and keeps its own note. What was wrong was
      // making the supervisor do that arithmetic: a woman with three
      // unresolved HIGH visits got three identical buttons, and clearing
      // one left the other two sitting in the escalation queue with
      // nothing on screen saying so. One clinical review of a patient
      // closes what that review actually covered.
      for (const v of openHighVisits) {
        await resolveRisk(v.visit_id, note);
      }
      const resolvedIds = new Set(openHighVisits.map((v) => v.visit_id));
      setData((prev) => ({
        ...prev,
        visits: prev.visits.map((v) =>
          resolvedIds.has(v.visit_id)
            ? {
                ...v,
                risk_resolved: true,
                risk_resolution_note: note,
                resolved_by_name: auth?.workerName || v.resolved_by_name,
              }
            : v,
        ),
      }));
      setResolving(false);
    } catch (err) {
      setResolveError(err.response?.data?.detail || "Could not resolve this risk.");
    } finally {
      setResolveSubmitting(false);
    }
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
  // Her open high-risk cases -- what a clinical review of this patient
  // would actually be closing. Newest first, same order as the timeline.
  const openHighVisits = data.visits.filter((v) => v.risk_level === "HIGH" && !v.risk_resolved);

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

        {/* One resolve action, on the person rather than on each visit.
            Resolving is a statement about this woman -- "I reviewed her,
            here is what I found" -- so it belongs beside her name, not
            repeated down a timeline of seven rows. */}
        {canOverride && openHighVisits.length > 0 && !resolving && (
          <button className="btn-resolve" onClick={startResolve}>
            Resolve after clinical review
          </button>
        )}
      </div>

      {resolving && (
        <div className="override-form resolve-panel">
          <label htmlFor="resolve-note">
            Clinical review note (required, at least 10 characters, kept in the audit trail)
          </label>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>
            This does not change any recorded risk classification -- it records that{" "}
            {data.patient_name.split(" ")[0]}&apos;s case was reviewed and why it is being closed out.
            {openHighVisits.length > 1 && (
              <> It closes all {openHighVisits.length} of her open high-risk visits under this one review.</>
            )}
          </p>
          <textarea
            id="resolve-note"
            value={resolveNote}
            onChange={(e) => setResolveNote(e.target.value)}
            placeholder="e.g. Called her directly, BP retest was normal -- referred her to the PHC as a precaution."
          />
          {resolveError && <p className="error">{resolveError}</p>}
          <div className="override-actions">
            <button className="btn-quiet" onClick={cancelResolve} disabled={resolveSubmitting}>
              Cancel
            </button>
            <button
              className="btn-submit"
              onClick={() => submitResolve(openHighVisits)}
              disabled={resolveSubmitting || resolveNote.trim().length < 10}
            >
              {resolveSubmitting ? "Saving…" : "Save & resolve"}
            </button>
          </div>
        </div>
      )}

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
                      {canOverride && !isOverriding && !v.risk_resolved && (
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

                    {/* A visit with no audio -- a historical record
                        entered before this system, or a seeded one -- has
                        no words to quote. Show what was actually measured
                        instead of an empty row, and never invent a quote
                        to fill the space. */}
                    {!v.transcript && summariseReadings(v.extracted) && (
                      <p className="readings">{summariseReadings(v.extracted)}</p>
                    )}

                    {v.risk_overridden && (
                      <div className="human-note">
                        <strong>
                          Corrected by {v.overridden_by_name || "a supervisor"}
                          {v.overridden_by_role ? ` (${v.overridden_by_role.toUpperCase()})` : ""}
                        </strong>
                        {v.risk_override_reason && <div className="muted">“{v.risk_override_reason}”</div>}
                      </div>
                    )}

                    {v.risk_resolved && (
                      <div className="human-note">
                        <strong>Resolved after clinical review by {v.resolved_by_name || "a supervisor"}</strong>
                        {v.risk_resolution_note && <div className="muted">“{v.risk_resolution_note}”</div>}
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
