import { useEffect, useState, useCallback, useRef } from "react";
import {
  fetchMetrics,
  fetchAnalytics,
  fetchEscalations,
  fetchFollowupCompliance,
  fetchWorkers,
  fetchHeatmap,
} from "../api/client";
import { useAuth } from "../context/AuthContext";
import AppShell from "../components/AppShell";
import StatStrip from "../components/StatStrip";
import { Section } from "../components/Surface";
import RiskBreakdownChart from "../components/RiskBreakdownChart";
import RiskHeatmap from "../components/RiskHeatmap";
import VisitsTrendChart from "../components/VisitsTrendChart";
import FollowupStatusChart from "../components/FollowupStatusChart";
import WorkerLeaderboardChart from "../components/WorkerLeaderboardChart";
import WorkerRoster from "../components/WorkerRoster";
import EscalationList from "../components/EscalationList";
import FollowupCompliance from "../components/FollowupCompliance";
import RegistrationQueue from "../components/RegistrationQueue";
import CoverPanel from "../components/CoverPanel";

const POLL_INTERVAL_MS = 60_000;

/* The supervisor's overview -- the same page for an ANM and a BMO, with
 * the backend deciding the scope. Ordered by what they came to find out:
 * the four figures and their shape over time, then who is behind on
 * visits, then the HIGH-risk cases nobody has picked up, then the
 * roster.
 *
 * Trends sit directly under the four figures rather than at the foot of
 * the page. They were last for a while, on the argument that nothing
 * here is as urgent as a mother whose 48-hour follow-up has lapsed and
 * that a supervisor should not scroll past four charts to find her. What
 * that missed is that the charts are the same four figures over time --
 * "27 past due" and the completion chart are one thought, and splitting
 * them by three sections meant nobody ever read the second half. The
 * urgent work has not moved down: the accountability table below now
 * opens closed, so it costs one screen instead of six. */
export default function DashboardPage() {
  const { auth } = useAuth();
  const isBmo = auth?.role === "bmo" || auth?.role === "admin";
  // An admin administers accounts, not care. The backend refuses her the
  // two endpoints below, which name patients; without this the page would
  // just show two permanently empty sections and a pair of 403s in the
  // console. Everything else here is counts and villages, which she keeps.
  const seesPatients = auth?.role !== "admin";

  const [metrics, setMetrics] = useState(null);
  const [heatmap, setHeatmap] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [escalations, setEscalations] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [compliance, setCompliance] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const activeRequest = useRef(null);

  const refresh = useCallback(async () => {
    if (activeRequest.current) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    const options = { signal: controller.signal };
    try {
      const [m, h, a, e, w, c] = await Promise.all([
        fetchMetrics(options),
        fetchHeatmap(options),
        fetchAnalytics(options),
        seesPatients ? fetchEscalations(options) : Promise.resolve([]),
        fetchWorkers(options),
        seesPatients ? fetchFollowupCompliance(options) : Promise.resolve(null),
      ]);
      if (controller.signal.aborted) return;
      setMetrics(m);
      setHeatmap(h);
      setAnalytics(a);
      setEscalations(e);
      setWorkers(w);
      setCompliance(c);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      if (controller.signal.aborted) return;
      controller.abort(); // Cancel sibling requests after one fails.
      setError(err.response?.data?.detail || "Failed to load dashboard data");
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => {
      clearInterval(interval);
      activeRequest.current?.abort();
      activeRequest.current = null;
    };
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

      {/* FR-08.1: the heatmap has to be the first thing on screen after
          the four headline numbers -- it is the opening beat of the demo
          script and the one view that answers "where" a supervisor
          should look next, which none of the tables below it do. */}
      <Section
        title="Risk heatmap"
        sub="Every village with a classified visit on record. Dot size is patient count; red is HIGH risk."
      >
        <div className="chart-card heatmap-card">
          <RiskHeatmap points={heatmap} />
        </div>
      </Section>

      {analytics && (
        <Section title="Trends" sub="The shape of the four numbers above, over time and across the sub-centre.">
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

      {/* An ANM only. A BMO has read-only access to individual records
          (SRS table 4), so the queue would be a panel of buttons she is
          not allowed to press, and an admin has the same queue on the
          admin panel where the rest of staff management lives.

          Collapses entirely when nobody is waiting: this page is about
          patients, and a permanent "nobody is waiting" panel above her
          escalations would tax the one screen meant to surface urgent
          things, every day, to say nothing happened. */}
      {auth?.role === "anm" && <RegistrationQueue collapseWhenEmpty onChange={refresh} />}

      {/* Above the accountability table on purpose. A follow-up that
          looks missed because the ASHA is on leave and a follow-up that
          is genuinely missed are the same red row -- the supervisor has
          to know which she is looking at before she reads the table, not
          after she has rung the worker. */}
      <CoverPanel />

      {seesPatients && (
        <Section
          title="Visit accountability"
          sub="Which ASHA owes which patient a follow-up, and which are past the deadline set for that patient's risk level."
        >
          <FollowupCompliance compliance={compliance} showSubCentre={isBmo} />
        </Section>
      )}

      {seesPatients && (
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
      )}

      <Section title={isBmo ? "ASHA workers" : "My sub-centre's ASHA workers"}>
        <WorkerRoster workers={workers} showSubCentre={isBmo} />
      </Section>
    </AppShell>
  );
}
