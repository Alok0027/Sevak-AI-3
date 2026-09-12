/* The page's structural pieces: a section, a grouped list, and a row
 * with a status rail.
 *
 * These exist so that pages stop reaching for a generic `.panel` div.
 * A page built from Section + StatusList reads as a document with
 * sections; a page built from six identical rounded cards reads as a
 * template, whatever colours you put in it. */

/** A titled region of the page. Deliberately *not* a card: a hairline
 * rule under the heading, and the content sits on the page. Six stacked
 * white boxes with shadows is the look we are getting away from. */
export function Section({ title, sub, aside, children, id }) {
  return (
    <section className="section" id={id}>
      {(title || aside) && (
        <div className="section-head">
          <div>
            {title && <h2>{title}</h2>}
            {sub && <p className="section-sub">{sub}</p>}
          </div>
          {aside && <div className="section-aside">{aside}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/** Related rows on one surface, divided by hairlines -- the web twin of
 * the mobile StatusGroup. */
export function StatusList({ children, className = "" }) {
  return <div className={`status-list ${className}`.trim()}>{children}</div>;
}

/** One row, carrying its severity as a 3px bar on the leading edge.
 *
 * `tone` is "high" | "medium" | "low" | "human" | null. Low resolves to
 * slate, so a settled patient stays visually quiet; "human" is indigo
 * and means a person made this call rather than the system. */
export function StatusRow({ tone, onClick, children, className = "" }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      type={onClick ? "button" : undefined}
      className={`status-row tone-${tone || "low"} ${onClick ? "is-clickable" : ""} ${className}`.trim()}
      onClick={onClick}
    >
      <span className="status-rail" aria-hidden="true" />
      <span className="status-row-body">{children}</span>
    </Tag>
  );
}

/** Severity as a word in its colour, never a filled badge.
 *
 * A row of solid colour chips is loud and, at a glance, tells you only
 * that something is categorised. The word carries the meaning; the
 * colour just lets you find it. Always renders the text, so this
 * survives a projector and colour-vision deficiency. */
export function RiskTag({ level }) {
  if (!level) return <span className="risk-tag tone-none">—</span>;
  return <span className={`risk-tag tone-${level.toLowerCase()}`}>{level}</span>;
}

/** A count in a small pill, for row summaries like "4 overdue". Tinted,
 * not filled -- see RiskTag. */
export function CountTag({ tone, children }) {
  return <span className={`count-tag tone-${tone}`}>{children}</span>;
}

/** An empty state that says what to do next rather than reporting
 * absence. Never "No data". */
export function Empty({ children }) {
  return <p className="empty">{children}</p>;
}
