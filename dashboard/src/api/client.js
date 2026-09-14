import axios from "axios";

// FR-08.3: dashboard must work on any modern browser without installation --
// plain REST calls to the FastAPI backend, no build-time coupling beyond this.
const baseURL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const client = axios.create({ baseURL });

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

export async function fetchMetrics() {
  const { data } = await client.get("/api/v1/dashboard/metrics");
  return data;
}

export async function fetchAnalytics() {
  const { data } = await client.get("/api/v1/dashboard/analytics");
  return data;
}

export async function fetchHeatmap() {
  const { data } = await client.get("/api/v1/dashboard/heatmap");
  return data.risk_points;
}

// FR-08 accountability: the row-level answer behind the follow-up chart --
// which ASHA owes which patient a visit, and how far past the deadline
// Agent 3 set for that patient's risk level.
export async function fetchFollowupCompliance() {
  const { data } = await client.get("/api/v1/dashboard/followup-compliance");
  return data;
}

export async function fetchEscalations() {
  const { data } = await client.get("/api/v1/escalations/pending");
  return data.escalations;
}

export async function fetchWorkers({ subCentreId, search } = {}) {
  const { data } = await client.get("/api/v1/workers", {
    params: { sub_centre_id: subCentreId || undefined, search: search || undefined },
  });
  return data.workers;
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
