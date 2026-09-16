import { Empty } from "./Surface";

/** "How much done, how much pending" -- follow-up completion, with
 * overdue split out from merely pending. From the analytics endpoint's
 * followup_status.
 *
 * This was a donut with a legend. Three values do not need a pie: a
 * donut makes you match colours to a legend to read three numbers, hides
 * the counts inside a tooltip, and is the single most template-looking
 * chart there is. A stacked proportion bar shows the same split in less
 * than half the height.
 *
 * The share leads and the count follows on hover. A supervisor comparing
 * her sub-centre against the block next door is asking "what
 * proportion", and 67% answers that in a glance where 140 needs a
 * division first. The count is the number she copies into a report, so
 * it is one hover away rather than gone -- and on a touch screen, where
 * there is no hover at all, both are simply shown.
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
        aria-label={segments.map((s) => `${s.label}: ${s.value} of ${total}`).join(", ")}
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
          // Focusable, so the count is reachable from the keyboard and
          // not only by pointer, and labelled with both figures so a
          // screen reader never depends on a hover it cannot perform.
          <div
            className="proportion-key"
            key={s.key}
            tabIndex={0}
            aria-label={`${s.label}: ${s.value} of ${total}, ${pct(s.value)} percent`}
          >
            <span className="proportion-key-head">
              <span className={`proportion-swatch tone-${s.key}`} aria-hidden="true" />
              {s.label}
            </span>
            {/* Both figures stay in the DOM and the card slides between
                them. Swapping the text on hover instead would reflow the
                line mid-animation, because "140" and "67%" are not the
                same width. */}
            <span className="proportion-figure" aria-hidden="true">
              <span className="proportion-share">{pct(s.value)}%</span>
              <span className="proportion-count">{s.value}</span>
            </span>
            <span className="proportion-of" aria-hidden="true">
              of {total}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
