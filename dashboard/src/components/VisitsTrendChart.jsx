import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

/** How much documentation is actually happening, day by day -- last 14 days,
 * straight from GET /dashboard/analytics (visits_by_day). */
export default function VisitsTrendChart({ data }) {
  const formatted = data.map((d) => ({
    ...d,
    label: new Date(d.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={formatted} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
        <defs>
          <linearGradient id="visitsFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#1f6f4a" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#1f6f4a" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={1} />
        <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
        <Tooltip labelFormatter={(_, payload) => payload?.[0]?.payload?.date} formatter={(v) => [v, "Visits"]} />
        <Area type="monotone" dataKey="count" stroke="#1f6f4a" strokeWidth={2} fill="url(#visitsFill)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}
