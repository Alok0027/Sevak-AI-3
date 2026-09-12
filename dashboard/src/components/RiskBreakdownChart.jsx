import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from "recharts";
import { TOKEN, axisProps, gridProps, tooltipProps } from "./chartTheme";

/** All-time risk classification breakdown, in the current role's scope.
 *
 * LOW is slate, not green, exactly as on the phone: a bar chart where
 * the biggest bar is a triumphant green says "mostly fine" when what the
 * section is for is finding the cases that aren't. */
export default function RiskBreakdownChart({ breakdown }) {
  const data = [
    { level: "HIGH", count: breakdown.high, fill: TOKEN.riskHigh },
    { level: "MEDIUM", count: breakdown.medium, fill: TOKEN.riskMedium },
    { level: "LOW", count: breakdown.low, fill: TOKEN.slate },
  ];

  return (
    <ResponsiveContainer width="100%" height={190}>
      <BarChart data={data} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
        <CartesianGrid {...gridProps} />
        <XAxis dataKey="level" {...axisProps} />
        <YAxis allowDecimals={false} {...axisProps} />
        <Tooltip {...tooltipProps} cursor={{ fill: TOKEN.sage }} />
        <Bar dataKey="count" name="Visits" radius={[3, 3, 0, 0]} maxBarSize={64}>
          {data.map((d) => (
            <Cell key={d.level} fill={d.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
