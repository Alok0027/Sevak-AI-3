import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { useNavigate } from "react-router-dom";

/** Top 10 workers by visits logged (FR-08 "worker performance metrics") --
 * bar tint reflects how many of those visits were HIGH risk. Click a bar to
 * drill into that worker. */
export default function WorkerLeaderboardChart({ leaderboard }) {
  const navigate = useNavigate();

  if (leaderboard.length === 0) {
    return <p className="empty-state">No visits logged yet.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(220, leaderboard.length * 32)}>
      <BarChart
        data={leaderboard}
        layout="vertical"
        margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
        onClick={(e) => {
          const worker = e?.activePayload?.[0]?.payload;
          if (worker) navigate(`/workers/${worker.worker_id}`);
        }}
      >
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
        <YAxis type="category" dataKey="worker_name" width={110} tick={{ fontSize: 11 }} />
        <Tooltip
          formatter={(v, name, entry) => [`${v} visits (${entry.payload.high_risk_count} HIGH)`, "Total"]}
        />
        <Bar dataKey="total_visits" radius={[0, 4, 4, 0]} cursor="pointer">
          {leaderboard.map((w) => (
            <Cell key={w.worker_id} fill={w.high_risk_count > 0 ? "#dc2626" : "#1f6f4a"} fillOpacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
