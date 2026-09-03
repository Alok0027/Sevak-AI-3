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

export async function fetchPatientHistory(patientId) {
  const { data } = await client.get(`/api/v1/patients/${patientId}/history`);
  return data;
}

export async function fetchHmisReport(workerId, month, year) {
  const { data } = await client.get(`/api/v1/reports/hmis/${workerId}/${month}/${year}`);
  return data;
}

export default client;
