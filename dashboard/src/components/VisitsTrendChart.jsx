import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  LabelList,
} from "recharts";
import { TOKEN, axisProps, gridProps, tooltipProps, valueLabelProps } from "./chartTheme";

/** How much documentation is actually happening, day by day -- last 14
 * days, straight from GET /dashboard/analytics (visits_by_day).
 *
 * Two figures are printed, not fourteen: the busiest day, and the most
 * recent one. A number over every point turns a trend line into a badly
 * drawn table -- you stop seeing the shape, which is the only reason to
 * draw a line in the first place. The two that are marked are the two
 * anyone actually asks for out loud ("what's our best day" and "how did
 * we do yesterday"), and the y-axis stays because reading a fortnight's
 * shape needs a scale that the rest of the points can be judged against.
 * Every other day is one hover away. */
export default function VisitsTrendChart({ data }) {
  const formatted = data.map((d) => ({
    ...d,
    label: new Date(d.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  }));

  // Ties go to the earliest peak, so the label does not hop between two
  // equal days every time the dashboard polls.
  const peak = formatted.reduce(
    (best, d, i) => (d.count > formatted[best].count ? i : best),
    0,
  );
  const last = formatted.length - 1;

  // A day with no visits gets no label: "0" floating over the baseline
  // reads as a stray axis tick, and a flat empty week would print a row
  // of them.
  const marked = new Set(
    [peak, last].filter((i) => formatted[i] && formatted[i].count > 0),
  );

  // Attached to the datum rather than resolved from the index Recharts
  // hands a render callback -- those two indices are not the same thing,
  // and the sibling leaderboard chart shipped a version that printed
  // every worker's figure against the wrong name because of it. An empty
  // string draws nothing.
  const points = formatted.map((d, i) => ({ ...d, mark: marked.has(i) ? d.count : "" }));

  return (
    <ResponsiveContainer width="100%" height={190}>
      <AreaChart data={points} margin={{ top: 20, right: 12, left: -22, bottom: 0 }}>
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
        >
          <LabelList dataKey="mark" position="top" offset={10} {...valueLabelProps} />
        </Area>
      </AreaChart>
    </ResponsiveContainer>
  );
}
