import { useEffect, useState, useCallback } from "react";
import { fetchMetrics, fetchAnalytics, fetchEscalations, fetchWorkers } from "../api/client";
import { useAuth } from "../context/AuthContext";
import MetricCard from "../components/MetricCard";
import RiskBreakdownChart from "../components/RiskBreakdownChart";
import VisitsTrendChart from "../components/VisitsTrendChart";
import FollowupStatusChart from "../components/FollowupStatusChart";
import WorkerLeaderboardChart from "../components/WorkerLeaderboardChart";
import WorkerRoster from "../components/WorkerRoster";
import EscalationList from "../components/EscalationList";

const POLL_INTERVAL_MS = 60_000;

export default function DashboardPage() {
  const { auth, logout } = useAuth();
  const isBmo = auth?.role === "bmo" || auth?.role === "admin";

  const [metrics, setMetrics] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [escalations, setEscalations] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [m, a, e, w] = await Promise.all([
        fetchMetrics(),
        fetchAnalytics(),
        fetchEscalations(),
        fetchWorkers(),
      ]);
      setMetrics(m);
      setAnalytics(a);
      setEscalations(e);
      setWorkers(w);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to load dashboard data");
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  return (
    <div className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h1>SevakAI {isBmo ? "District Dashboard" : "Sub-Centre Dashboard"}</h1>
          <p className="subtitle">
            {isBmo ? "District-wide view across all sub-centres" : "Scoped to your sub-centre only"}
          </p>
        </div>
        <div className="header-actions">
          {lastUpdated && <span className="last-updated">Updated {lastUpdated.toLocaleTimeString()}</span>}
          <span className="role-badge">{auth?.role}</span>
          <button onClick={logout}>Sign out</button>
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      {metrics && (
        <section className="metrics-row">
          <MetricCard label="Visits Today" value={metrics.total_visits_today} accent="#2563eb" />
          <MetricCard label="High Risk Cases" value={metrics.high_risk_cases} accent="#dc2626" />
          <MetricCard label="Pending Follow-ups" value={metrics.pending_followups} accent="#d97706" />
          <MetricCard
            label="HMIS Completion"
            value={`${Math.round(metrics.hmis_completion_rate * 100)}%`}
            accent="#16a34a"
          />
        </section>
      )}

      {analytics && (
        <section className="charts-grid">
          <div className="panel">
            <h2>Visits Over Time (14 days)</h2>
            <VisitsTrendChart data={analytics.visits_by_day} />
          </div>
          <div className="panel">
            <h2>Follow-up Completion</h2>
            <FollowupStatusChart status={analytics.followup_status} />
          </div>
          <div className="panel">
            <h2>Risk Distribution</h2>
            <RiskBreakdownChart breakdown={analytics.risk_breakdown} />
          </div>
          <div className="panel">
            <h2>Worker Leaderboard</h2>
            <WorkerLeaderboardChart leaderboard={analytics.worker_leaderboard} />
          </div>
        </section>
      )}

      <section className="panel">
        <h2>{isBmo ? "All ASHA Workers" : "My Sub-Centre's ASHA Workers"}</h2>
        <WorkerRoster workers={workers} showSubCentre={isBmo} />
      </section>

      <section className="panel">
        <h2>Unactioned HIGH Risk Cases</h2>
        <EscalationList escalations={escalations} showSubCentre={isBmo} />
      </section>
    </div>
  );
}
