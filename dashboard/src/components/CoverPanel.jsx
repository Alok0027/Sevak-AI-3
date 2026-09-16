import { useCallback, useEffect, useState } from "react";
import { fetchAbsences } from "../api/client";
import { Section, StatusList, StatusRow } from "./Surface";

/** Who is away, and who is carrying their patients.
 *
 * The failure this replaces is not dramatic and that is exactly why it
 * persists: an ASHA goes away for a fortnight, tells a colleague at the
 * sub-centre, and her supervisor finds out when a follow-up is missed.
 * Now the ASHA arranges cover in the app, ownership never moves, and it
 * shows up here the moment she sets it.
 *
 * Deliberately not a control. An ANM watching this page cannot end
 * somebody's leave from it, because she did not arrange it and the
 * worker who did is the one who knows whether she is back. What the
 * supervisor needs is to *know*, which is what this gives her.
 *
 * Collapses when nobody is away -- same reasoning as the registration
 * queue above it. Leave is rare, and a permanent "nobody is away" panel
 * on the page meant to surface urgent things is a tax paid every day to
 * report that nothing happened.
 */
export default function CoverPanel({ collapseWhenEmpty = true }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    fetchAbsences()
      .then((data) => {
        setRows(data);
        setError(null);
      })
      .catch((err) => setError(err.response?.data?.detail || "Could not load leave records"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  if (loading) return null;
  if (error) {
    return (
      <Section title="Cover">
        <p className="error">{error}</p>
      </Section>
    );
  }
  if (rows.length === 0 && collapseWhenEmpty) return null;

  const active = rows.filter((a) => a.in_effect).length;

  return (
    <Section
      title="Who is away"
      sub="Leave the workers arranged themselves. The patients stay with whoever was assigned them — the covering worker can see them and record visits until the day the leave ends."
      aside={
        rows.length > 0 ? (
          <span className="chip">
            {active > 0 ? `${active} away now` : `${rows.length} booked`}
          </span>
        ) : null
      }
    >
      {rows.length === 0 ? (
        <p className="muted">Nobody is on leave.</p>
      ) : (
        <StatusList>
          {rows.map((a) => (
            // "human", not a risk tone. Somebody arranged this; it is not
            // a thing that went wrong, and painting it amber would put it
            // in the same visual language as a missed follow-up.
            <StatusRow key={a.absence_id} tone="human">
              <span className="row-main">
                <span className="cell-strong">{a.worker_name}</span>
                {a.worker_code && <span className="worker-code"> {a.worker_code}</span>}
                <span className="cell-sub">
                  {formatWindow(a)}
                  {a.reason ? ` · ${a.reason}` : ""}
                </span>
              </span>
              <span className="row-side">
                <span className="cover-note">
                  {a.in_effect ? "Covered by" : "Will be covered by"} {a.covering_worker_name}
                </span>
                {a.covering_worker_code && (
                  <span className="cell-sub">{a.covering_worker_code}</span>
                )}
              </span>
            </StatusRow>
          ))}
        </StatusList>
      )}
    </Section>
  );
}

function formatWindow(a) {
  const opts = { day: "numeric", month: "short" };
  const from = new Date(a.starts_on).toLocaleDateString(undefined, opts);
  const to = new Date(a.ends_on).toLocaleDateString(undefined, opts);
  return `${from} – ${to}`;
}
