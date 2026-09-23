import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import WorkerDetailPage from "./pages/WorkerDetailPage";
import PatientsPage from "./pages/PatientsPage";
import PatientDetailPage from "./pages/PatientDetailPage";
import AdminPage from "./pages/AdminPage";
import "./App.css";

function ProtectedRoute({ children }) {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  return children;
}

function AdminRoute({ children }) {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  // The backend already 403s any non-admin call to /api/v1/admin/* -- this
  // is just so a non-admin who navigates here directly sees the normal
  // dashboard instead of a page full of failed requests.
  if (auth.role !== "admin") return <Navigate to="/" replace />;
  return children;
}

function CareRoute({ children }) {
  // The mirror of AdminRoute. The backend is the real enforcement -- it
  // 403s a patient-data call from an admin token -- and this just keeps a
  // stray URL from rendering a page whose every request will fail.
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  if (auth.role === "admin") return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/workers/:workerId"
            element={
              <ProtectedRoute>
                <WorkerDetailPage />
              </ProtectedRoute>
            }
          />
          {/* Patient routes are closed to the admin role, matching the
              backend: an admin who types the URL is sent to the Overview
              rather than shown a page that can only 403. */}
          <Route
            path="/patients"
            element={
              <ProtectedRoute>
                <CareRoute>
                  <PatientsPage />
                </CareRoute>
              </ProtectedRoute>
            }
          />
          <Route
            path="/patients/:patientId"
            element={
              <ProtectedRoute>
                <CareRoute>
                  <PatientDetailPage />
                </CareRoute>
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <AdminRoute>
                <AdminPage />
              </AdminRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
