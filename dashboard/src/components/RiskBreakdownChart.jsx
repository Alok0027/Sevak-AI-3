import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from "recharts";

const COLORS = { HIGH: "#dc2626", MEDIUM: "#d97706", LOW: "#16a34a" };

/** All-time risk classification breakdown (in the current role's scope). */
export default function RiskBreakdownChart({ breakdown }) {
  const data = [
    { level: "HIGH", count: breakdown.high },
    { level: "MEDIUM", count: breakdown.medium },
    { level: "LOW", count: breakdown.low },
  ];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="level" tick={{ fontSize: 11 }} />
        <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
        <Tooltip />
        <Bar dataKey="count" radius={[4, 4, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.level} fill={COLORS[d.level]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
