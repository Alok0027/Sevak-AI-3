/* The headline figures as one divided strip rather than four cards.
 *
 * Four tinted cards, each with its own accent colour, read as four
 * competing things and are the single most recognisable shape in
 * dashboard templates. One surface with hairline divisions says "this is
 * a summary" and leaves the page for the work.
 *
 * Colour is reserved for figures that mean something is wrong. A count
 * of visits logged today is not an alarm and gets ink; a HIGH-risk
 * backlog is, and gets the risk colour. Everything coloured red on this
 * strip is something a supervisor has to act on -- which is only true if
 * most of it isn't. */
export default function StatStrip({ stats }) {
  return (
    <div className="stat-strip">
      {stats.map((s) => (
        <div className="stat" key={s.label}>
          <span className={s.tone ? `stat-value num tone-${s.tone}` : "stat-value num"}>
            {s.value}
          </span>
          <span className="stat-label">{s.label}</span>
          {s.note && <span className="stat-note">{s.note}</span>}
        </div>
      ))}
    </div>
  );
}
