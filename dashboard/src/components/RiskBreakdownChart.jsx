import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LabelList } from "recharts";
import { TOKEN, axisProps, tooltipProps, valueLabelProps } from "./chartTheme";

/** All-time risk classification breakdown, in the current role's scope.
 *
 * LOW is slate, not green, exactly as on the phone: a bar chart where
 * the biggest bar is a triumphant green says "mostly fine" when what the
 * section is for is finding the cases that aren't.
 *
 * Three bars, each carrying its own figure, so the y-axis and the
 * gridlines have come off. They existed to let you estimate a value from
 * a bar's height; once the value is printed, an axis, a grid and a label
 * are three ways to read the same number and two of them are ink spent
 * on nothing.
 *
 * On colour: HIGH and MEDIUM are near-identical to a red-green
 * colourblind reader (measured at ΔE 0.7 deutan). That is survivable
 * only because colour is not what identifies these bars -- the words
 * HIGH, MEDIUM and LOW sit under them and the counts above them, so the
 * chart reads correctly in greyscale. Here the hue says severity a
 * second time. It would be a real fault in any chart where the hue was
 * the only key. */
export default function RiskBreakdownChart({ breakdown }) {
  const data = [
    { level: "HIGH", count: breakdown.high, fill: TOKEN.riskHigh },
    { level: "MEDIUM", count: breakdown.medium, fill: TOKEN.riskMedium },
    { level: "LOW", count: breakdown.low, fill: TOKEN.slate },
  ];

  return (
    <ResponsiveContainer width="100%" height={190}>
      {/* The top margin is what the figures stand in. Without it the
          label on the tallest bar is clipped by the plot area. */}
      <BarChart data={data} margin={{ top: 22, right: 4, left: 4, bottom: 0 }}>
        {/* Hidden, not removed. This is the value axis, and it is what
            gives the bars a numeric domain to be measured against;
            deleting it outright is how the sibling leaderboard chart
            lost two of its bars entirely. `hide` takes the ticks off and
            keeps the scale. */}
        <YAxis allowDecimals={false} hide />
        <XAxis dataKey="level" {...axisProps} />
        <Tooltip {...tooltipProps} cursor={{ fill: TOKEN.sage }} />
        <Bar dataKey="count" name="Visits" radius={[3, 3, 0, 0]} maxBarSize={64}>
          <LabelList dataKey="count" position="top" offset={8} {...valueLabelProps} />
          {data.map((d) => (
            <Cell key={d.level} fill={d.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
