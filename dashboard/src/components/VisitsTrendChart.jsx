import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { TOKEN, axisProps, gridProps, tooltipProps } from "./chartTheme";

/** How much documentation is actually happening, day by day -- last 14
 * days, straight from GET /dashboard/analytics (visits_by_day).
 *
 * No printed figures. The bar charts carry theirs because they have
 * three and seven marks; this has fourteen, and a number on a line chart
 * is a number the eye stops on -- which is the opposite of what a
 * fortnight of visits is for. The shape is the message: a flat stretch
 * is a week nobody documented. The y-axis gives the scale and every
 * single day is one hover away. */
export default function VisitsTrendChart({ data }) {
  const formatted = data.map((d) => ({
    ...d,
    label: new Date(d.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  }));

  return (
    <ResponsiveContainer width="100%" height={190}>
      <AreaChart data={formatted} margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
        <defs>
          <linearGradient id="visitsFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={TOKEN.forest} stopOpacity={0.18} />
            <stop offset="100%" stopColor={TOKEN.forest} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid {...gridProps} />
        <XAxis dataKey="label" interval={1} {...axisProps} />
        <YAxis allowDecimals={false} {...axisProps} />
        <Tooltip
          {...tooltipProps}
          cursor={{ stroke: TOKEN.slate, strokeWidth: 1, strokeDasharray: "3 3" }}
          labelFormatter={(label) => label}
          formatter={(v) => [v, "Visits"]}
        />
        <Area
          type="monotone"
          dataKey="count"
          stroke={TOKEN.forest}
          strokeWidth={2}
          fill="url(#visitsFill)"
          dot={false}
          activeDot={{ r: 4, fill: TOKEN.forest, stroke: "#fff", strokeWidth: 2 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
