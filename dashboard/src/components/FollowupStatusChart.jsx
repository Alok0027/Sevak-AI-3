import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";

const COLORS = { Done: "#16a34a", Pending: "#d97706", Overdue: "#dc2626" };

/** "How much done, how much pending" -- follow-up task completion, split
 * out overdue (past due_at) from merely pending, straight from the
 * analytics endpoint's followup_status. */
export default function FollowupStatusChart({ status }) {
  const data = [
    { name: "Done", value: status.done },
    { name: "Pending", value: status.pending },
    { name: "Overdue", value: status.overdue },
  ].filter((d) => d.value > 0);

  const total = status.done + status.pending + status.overdue;

  if (total === 0) {
    return <p className="empty-state">No follow-up tasks recorded yet.</p>;
  }

  return (
    <div className="donut-wrap">
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={2}>
            {data.map((d) => (
              <Cell key={d.name} fill={COLORS[d.name]} />
            ))}
          </Pie>
          <Tooltip formatter={(v, name) => [`${v} (${Math.round((v / total) * 100)}%)`, name]} />
          <Legend verticalAlign="bottom" height={24} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
