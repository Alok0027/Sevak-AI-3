import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { useNavigate } from "react-router-dom";
import { TOKEN, axisProps, tooltipProps } from "./chartTheme";
import { Empty } from "./Surface";

/** Top workers by visits logged (FR-08 "worker performance metrics").
 * A bar is tinted red only when that worker is carrying HIGH-risk cases,
 * so the chart answers "who is busy" and "who is carrying the hard
 * ones" at the same time. Click a bar to drill in. */
export default function WorkerLeaderboardChart({ leaderboard }) {
  const navigate = useNavigate();

  if (leaderboard.length === 0) {
    return <Empty>No visits logged yet. Bars appear here as ASHA workers record their first visits.</Empty>;
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(190, leaderboard.length * 30)}>
      <BarChart
        data={leaderboard}
        layout="vertical"
        margin={{ top: 0, right: 12, left: 4, bottom: 0 }}
        onClick={(e) => {
          const worker = e?.activePayload?.[0]?.payload;
          if (worker) navigate(`/workers/${worker.worker_id}`);
        }}
      >
        <XAxis type="number" allowDecimals={false} {...axisProps} />
        <YAxis type="category" dataKey="worker_name" width={112} {...axisProps} />
        <Tooltip
          {...tooltipProps}
          cursor={{ fill: TOKEN.sage }}
          formatter={(v, name, entry) => [
            `${v} visits · ${entry.payload.high_risk_count} HIGH`,
            "Logged",
          ]}
        />
        <Bar dataKey="total_visits" radius={[0, 3, 3, 0]} cursor="pointer" maxBarSize={18}>
          {leaderboard.map((w) => (
            <Cell key={w.worker_id} fill={w.high_risk_count > 0 ? TOKEN.riskHigh : TOKEN.forest} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
