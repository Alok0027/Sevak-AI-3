import { useEffect, useState, useCallback } from "react";
import {
  fetchMetrics,
  fetchAnalytics,
  fetchEscalations,
  fetchFollowupCompliance,
  fetchWorkers,
} from "../api/client";
import { useAuth } from "../context/AuthContext";
import AppShell from "../components/AppShell";
import StatStrip from "../components/StatStrip";
import { Section } from "../components/Surface";
import RiskBreakdownChart from "../components/RiskBreakdownChart";
import VisitsTrendChart from "../components/VisitsTrendChart";
import FollowupStatusChart from "../components/FollowupStatusChart";
import WorkerLeaderboardChart from "../components/WorkerLeaderboardChart";
import WorkerRoster from "../components/WorkerRoster";
import EscalationList from "../components/EscalationList";
import FollowupCompliance from "../components/FollowupCompliance";

const POLL_INTERVAL_MS = 60_000;

/* The supervisor's overview -- the same page for an ANM and a BMO, with
 * the backend deciding the scope. Ordered by what they came to find out:
 * the four figures, then who is behind on visits, then the HIGH-risk
 * cases nobody has picked up, then the roster, then the trends.
 *
 * That order is deliberate and it is not the order the first version
 * used. Charts first is the dashboard-template instinct; but nothing on
 * this page is as urgent as a mother whose 48-hour follow-up lapsed, and
 * a supervisor who has to scroll past four charts to find her is being
 * shown the decoration before the work. Trends go last, because they are
 * what you read when nothing is on fire. */
export default function DashboardPage() {
  const { auth } = useAuth();
  const isBmo = auth?.role === "bmo" || auth?.role === "admin";

  const [metrics, setMetrics] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [escalations, setEscalations] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [compliance, setCompliance] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [m, a, e, w, c] = await Promise.all([
        fetchMetrics(),
        fetchAnalytics(),
        fetchEscalations(),
        fetchWorkers(),
        fetchFollowupCompliance(),
      ]);
      setMetrics(m);
      setAnalytics(a);
      setEscalations(e);
      setWorkers(w);
      setCompliance(c);
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

  const overdue = compliance?.total_overdue ?? 0;

  return (
    <AppShell
      title="Overview"
      scope={isBmo ? "District-wide — every sub-centre" : "Scoped to your sub-centre"}
      meta={
        lastUpdated
          ? `Live · updated ${lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
          : "Loading…"
      }
      actions={
        <button className="btn-quiet" onClick={refresh}>
          Refresh
        </button>
      }
    >
      {error && <p className="error">{error}</p>}

      {metrics && (
        <StatStrip
          stats={[
            { label: "Visits today", value: metrics.total_visits_today },
            {
              label: "HIGH risk cases",
              value: metrics.high_risk_cases,
              tone: metrics.high_risk_cases > 0 ? "high" : null,
            },
            {
              label: "Pending follow-ups",
              value: metrics.pending_followups,
              tone: overdue > 0 ? "medium" : null,
              note: overdue > 0 ? `${overdue} past due` : null,
            },
            {
              label: "HMIS completion",
              value: `${Math.round(metrics.hmis_completion_rate * 100)}%`,
            },
          ]}
        />
      )}

      <Section
        title="Visit accountability"
        sub="Which ASHA owes which patient a follow-up, and which are past the deadline set for that patient's risk level."
      >
        <FollowupCompliance compliance={compliance} showSubCentre={isBmo} />
      </Section>

      <Section
        title="Unactioned HIGH risk cases"
        sub="Flagged by the risk agent and not yet picked up. Past 48 hours they escalate automatically."
        aside={
          escalations.length > 0 ? (
            <span className="chip">{escalations.length} waiting</span>
          ) : null
        }
      >
        <EscalationList escalations={escalations} showSubCentre={isBmo} />
      </Section>

      <Section title={isBmo ? "ASHA workers" : "My sub-centre's ASHA workers"}>
        <WorkerRoster workers={workers} showSubCentre={isBmo} />
      </Section>

      {analytics && (
        <Section title="Trends" sub="The picture behind the numbers above.">
          <div className="section-grid">
            <div className="chart-card">
              <span className="chart-title">Visits logged</span>
              <span className="chart-sub">Last 14 days</span>
              <VisitsTrendChart data={analytics.visits_by_day} />
            </div>
            <div className="chart-card">
              <span className="chart-title">Follow-up completion</span>
              <span className="chart-sub">All tasks ever created</span>
              <FollowupStatusChart status={analytics.followup_status} />
            </div>
            <div className="chart-card">
              <span className="chart-title">Risk distribution</span>
              <span className="chart-sub">Every visit classified to date</span>
              <RiskBreakdownChart breakdown={analytics.risk_breakdown} />
            </div>
            <div className="chart-card">
              <span className="chart-title">Visits by worker</span>
              <span className="chart-sub">Red marks a worker carrying HIGH-risk cases</span>
              <WorkerLeaderboardChart leaderboard={analytics.worker_leaderboard} />
            </div>
          </div>
        </Section>
      )}
    </AppShell>
  );
}
