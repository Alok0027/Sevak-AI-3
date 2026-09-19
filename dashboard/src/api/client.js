import axios from "axios";

// FR-08.3: dashboard must work on any modern browser without installation --
// plain REST calls to the FastAPI backend, no build-time coupling beyond this.
const configured = (import.meta.env.VITE_API_BASE_URL || "").trim();

// The localhost default is a *development* convenience and nothing else.
//
// It used to apply to production builds too, and that quietly cost hours.
// A deployed dashboard with no VITE_API_BASE_URL falls back to calling
// http://localhost:8000 -- the viewer's own laptop. On an https origin the
// browser refuses that as mixed content and never sends the request at
// all, so the Network tab is empty, the console says nothing useful, and
// the screen says "Login failed" as though the PIN were wrong.
//
// A deployment that has not been told where its API is should say so, in
// those words, on the screen where somebody is trying to sign in.
export const apiBaseUrl = configured || (import.meta.env.DEV ? "http://localhost:8000" : "");

/** A sentence to put on the login screen, or null when the config is fine. */
export const apiConfigProblem = (() => {
  if (!configured && !import.meta.env.DEV) {
    return (
      "This build was not told where the API is. Set VITE_API_BASE_URL in the " +
      "hosting project's environment variables and redeploy. Note that a variable " +
      "scoped to Production only does not apply to a preview deployment."
    );
  }
  // Same failure, different cause: an https page cannot call an http API,
  // and the browser blocks it before a request exists to debug.
  if (
    configured.startsWith("http://") &&
    typeof window !== "undefined" &&
    window.location.protocol === "https:"
  ) {
    return (
      `This page is served over https but VITE_API_BASE_URL is ${configured}. ` +
      "The browser blocks that as mixed content, so the request is never sent. " +
      "Use an https API address."
    );
  }
  return null;
})();

const client = axios.create({ baseURL: apiBaseUrl, timeout: 60_000 });

// Fail with the real reason rather than letting axios attempt a call that
// cannot work and reporting it as a generic network error.
client.interceptors.request.use((config) => {
  if (apiConfigProblem) return Promise.reject(new Error(apiConfigProblem));
  return config;
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("sevakai_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// A token expires after 8 hours, which for a dashboard left open overnight
// means every poll comes back 401. Without this the page keeps retrying on
// its 60-second timer indefinitely -- the user sees a stale screen with an
// error banner, and the backend log fills with unauthorised requests that
// look like an attack.
//
// On a 401 anywhere except the login call itself, drop the dead credentials
// and go to the login screen. A full navigation rather than a React redirect
// is deliberate: it also tears down every in-flight poller, which is the
// thing that was actually looping.
client.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const isLoginAttempt = error.config?.url?.includes("/auth/login");
    if (status === 401 && !isLoginAttempt) {
      localStorage.removeItem("sevakai_token");
      localStorage.removeItem("sevakai_role");
      localStorage.removeItem("sevakai_worker_id");
      if (!window.location.pathname.startsWith("/login")) {
        window.location.assign("/login?expired=1");
      }
    }
    return Promise.reject(error);
  },
);

export async function login(phone, pin) {
  const { data } = await client.post("/api/v1/auth/login", { phone, pin });
  return data;
}

export async function fetchMetrics({ signal } = {}) {
  const { data } = await client.get("/api/v1/dashboard/metrics", { signal });
  return data;
}

export async function resolveRisk(visitId, note) {
  const { data } = await client.post(`/api/v1/visits/${visitId}/resolve-risk`, { note });
  return data;
}

export async function fetchAnalytics({ signal } = {}) {
  const { data } = await client.get("/api/v1/dashboard/analytics", { signal });
  return data;
}

export async function fetchHeatmap() {
  const { data } = await client.get("/api/v1/dashboard/heatmap");
  return data.risk_points;
}

// FR-08 accountability: the row-level answer behind the follow-up chart --
// which ASHA owes which patient a visit, and how far past the deadline
// Agent 3 set for that patient's risk level.
export async function fetchFollowupCompliance({ signal } = {}) {
  const { data } = await client.get("/api/v1/dashboard/followup-compliance", { signal });
  return data;
}

export async function fetchEscalations({ signal } = {}) {
  const { data } = await client.get("/api/v1/escalations/pending", { signal });
  return data.escalations;
}

export async function fetchWorkers({ subCentreId, search, signal } = {}) {
  const { data } = await client.get("/api/v1/workers", {
    params: { sub_centre_id: subCentreId || undefined, search: search || undefined },
    signal,
  });
  return data.workers;
}

// Who is on leave right now, and who is carrying their patients.
// Scoped server-side: an ANM sees her own sub-centre, a BMO the district.
export async function fetchAbsences() {
  const { data } = await client.get("/api/v1/workers/absences");
  return data.absences;
}

// Permanent: the whole caseload moves to another ASHA and stays there.
// Not the same thing as leave cover, which lapses on its own and leaves
// ownership alone -- this is the one a supervisor uses when somebody has
// left the post, and it is restricted to an ANM for that reason.
export async function reassignCaseload(fromWorkerId, toWorkerId, reason) {
  const { data } = await client.post(
    `/api/v1/patients/caseload/${fromWorkerId}/reassign`,
    { to_worker_id: toWorkerId, reason },
  );
  return data;
}

export async function fetchWorkerHistory(workerId) {
  const { data } = await client.get(`/api/v1/workers/${workerId}/history`);
  return data;
}

// FR-03.3: ANM correction of the AI's risk call, with a mandatory reason.
// Only the ASHA who recorded the visit or her ANM can call this -- the
// backend enforces that and 403s anyone else.
export async function overrideRisk(visitId, newRiskLevel, reason) {
  const { data } = await client.post(`/api/v1/visits/${visitId}/risk-override`, {
    new_risk_level: newRiskLevel,
    reason,
  });
  return data;
}

export async function fetchPatientHistory(patientId) {
  const { data } = await client.get(`/api/v1/patients/${patientId}/history`);
  return data;
}

// FR-08 drill-down: every patient across the ANM's sub-centre, or (BMO/
// Admin) the whole district -- the cross-worker view GET /patients/{id}
// (one ASHA's own list) can't give you. Gender/risk/registration-date
// filters are applied client-side on the returned array (see PatientsPage).
export async function fetchAllPatients({ subCentreId } = {}) {
  const { data } = await client.get("/api/v1/patients", {
    params: { sub_centre_id: subCentreId || undefined },
  });
  return data.patients;
}

// Admin panel (NFR-SC1/SC4 + the 'admin' role finally having somewhere to
// go): district-wide staff directory across all four roles (the ASHA-only
// roster above can't show this) and the audit trail viewer.
export async function fetchStaff({ role, status } = {}) {
  const { data } = await client.get("/api/v1/admin/staff", {
    params: { role: role || undefined, status: status || undefined },
  });
  // The caller wants the rows; the pending count rides along on the object
  // so the panel can badge the queue without a second request.
  return Object.assign(data.staff, { pendingCount: data.pending_count ?? 0 });
}

// Pending registrations, scoped by the backend: an ANM sees the ASHAs who
// named her sub-centre, an admin sees everyone. Separate from fetchStaff,
// which is the whole district staff directory and stays admin-only.
export async function fetchRegistrations() {
  const { data } = await client.get("/api/v1/admin/registrations");
  return data.staff;
}

// A worker who registered in the app is waiting on one of these two calls.
// Until an admin makes the decision she cannot sign in at all, so this is
// not an administrative nicety -- it is the last step of her onboarding.
export async function approveStaff(workerId, reason) {
  const { data } = await client.post(`/api/v1/admin/staff/${workerId}/approve`, {
    reason: reason || null,
  });
  return data;
}

export async function rejectStaff(workerId, reason) {
  const { data } = await client.post(`/api/v1/admin/staff/${workerId}/reject`, { reason });
  return data;
}

export async function createStaff(payload) {
  const { data } = await client.post("/api/v1/admin/staff", payload);
  return data;
}

export async function fetchAuditLog({ actionType, actorSearch, dateFrom, dateTo, limit } = {}) {
  const { data } = await client.get("/api/v1/admin/audit-log", {
    params: {
      action_type: actionType || undefined,
      actor_search: actorSearch || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      limit: limit || undefined,
    },
  });
  return data.entries;
}

export async function fetchHmisReport(workerId, month, year) {
  const { data } = await client.get(`/api/v1/reports/hmis/${workerId}/${month}/${year}`);
  return data;
}

export default client;
