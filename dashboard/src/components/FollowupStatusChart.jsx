import { Empty } from "./Surface";

/** "How much done, how much pending" -- follow-up completion, with
 * overdue split out from merely pending. From the analytics endpoint's
 * followup_status.
 *
 * This was a donut with a legend. Three values do not need a pie: a
 * donut makes you match colours to a legend to read three numbers, hides
 * the counts inside a tooltip, and is the single most template-looking
 * chart there is. A stacked proportion bar shows the same split *and*
 * keeps all three counts on screen, in less than half the height.
 *
 * Done is forest -- the good outcome, and the one place a positive reads
 * as brand rather than as a risk level. */
export default function FollowupStatusChart({ status }) {
  const total = status.done + status.pending + status.overdue;

  if (total === 0) {
    return <Empty>No follow-up tasks recorded yet. They are created automatically after a visit.</Empty>;
  }

  const segments = [
    { key: "done", label: "Done", value: status.done },
    { key: "pending", label: "Pending", value: status.pending },
    { key: "overdue", label: "Overdue", value: status.overdue },
  ];

  const pct = (v) => Math.round((v / total) * 100);

  return (
    <div className="proportion">
      <div
        className="proportion-bar"
        role="img"
        aria-label={segments.map((s) => `${s.label}: ${s.value}`).join(", ")}
      >
        {segments
          .filter((s) => s.value > 0)
          .map((s) => (
            <div
              key={s.key}
              className={`proportion-seg tone-${s.key}`}
              style={{ width: `${(s.value / total) * 100}%` }}
            />
          ))}
      </div>
      <div className="proportion-keys">
        {segments.map((s) => (
          <div className="proportion-key" key={s.key}>
            <span className="proportion-key-head">
              <span className={`proportion-swatch tone-${s.key}`} aria-hidden="true" />
              {s.label}
            </span>
            <span className="proportion-value">
              {s.value}
              <span className="proportion-pct"> · {pct(s.value)}%</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
