import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LabelList } from "recharts";
import { useNavigate } from "react-router-dom";
import { TOKEN, axisProps, tooltipProps, valueLabelProps } from "./chartTheme";
import { Empty } from "./Surface";

/** Top workers by visits logged (FR-08 "worker performance metrics").
 * A bar is tinted red only when that worker is carrying HIGH-risk cases,
 * so the chart answers "who is busy" and "who is carrying the hard
 * ones" at the same time. Click a bar to drill in.
 *
 * The figure at the end of each bar replaces the x-axis, which was only
 * ever a way of guessing at the number now printed there.
 *
 * It also fixes something the colour alone could not carry. Forest and
 * the risk red separate by ΔE 7.3 under protanopia -- close enough that
 * for a red-green colourblind supervisor the red bars were not reliably
 * distinguishable from the rest, and "red means she is carrying HIGH
 * cases" was the chart's whole second message. Printing "· 6 HIGH"
 * beside the count says it in words, so the hue is now emphasis rather
 * than the only key. Workers with none get a bare number, and their
 * bars stay quiet. */
export default function WorkerLeaderboardChart({ leaderboard }) {
  const navigate = useNavigate();

  if (leaderboard.length === 0) {
    return <Empty>No visits logged yet. Bars appear here as ASHA workers record their first visits.</Empty>;
  }

  // Composed here, on the datum, so the label is resolved by dataKey the
  // same way the bar length is.
  //
  // The first version of this rendered the label from a content callback
  // that looked the worker up by the index Recharts passed in. That index
  // is not the index into this array, so every label was attached to the
  // wrong worker -- and because each one was a real number from a real
  // row, it looked entirely plausible. Dayamai Parikh was credited with
  // somebody else's 27 visits. A wrong number that looks right is the
  // worst possible failure on a performance chart, so there is no
  // arithmetic on indices here at all.
  const data = leaderboard.map((w) => ({
    ...w,
    label: w.high_risk_count > 0 ? `${w.total_visits} · ${w.high_risk_count} HIGH` : `${w.total_visits}`,
  }));

  return (
    <ResponsiveContainer width="100%" height={Math.max(190, data.length * 30)}>
      <BarChart
        data={data}
        layout="vertical"
        // The right margin is the label's room. Too little and the
        // busiest worker -- the one whose bar reaches furthest -- is the
        // one whose figure gets clipped.
        margin={{ top: 0, right: 84, left: 4, bottom: 0 }}
        onClick={(e) => {
          const worker = e?.activePayload?.[0]?.payload;
          if (worker) navigate(`/workers/${worker.worker_id}`);
        }}
      >
        {/* Hidden, not removed. On a horizontal bar chart this is the
            value axis: it defines the scale the bars are measured on.
            Deleting it outright (on the reasoning that the printed
            figures had replaced it) left Recharts without a numeric
            domain, and the two busiest workers rendered with no bar at
            all. `hide` takes the ticks off the screen and leaves the
            scale intact. */}
        <XAxis type="number" allowDecimals={false} hide />
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
          <LabelList dataKey="label" position="right" offset={8} {...valueLabelProps} />
          {data.map((w) => (
            <Cell key={w.worker_id} fill={w.high_risk_count > 0 ? TOKEN.riskHigh : TOKEN.forest} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
