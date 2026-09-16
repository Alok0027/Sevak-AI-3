/* One place where the chart library meets the design system.
 *
 * Recharts takes colours and type as inline props, so without this every
 * chart file ends up with its own hardcoded hex and its own idea of what
 * a tick label looks like -- which is how the first version of this
 * dashboard ended up with four charts in four palettes, none of them the
 * product's. These values mirror styles/tokens.css.
 *
 * Read from the stylesheet at module load so there is still exactly one
 * source of truth: change a token, every chart follows. */
const css = getComputedStyle(document.documentElement);
const read = (name, fallback) => css.getPropertyValue(name).trim() || fallback;

export const TOKEN = {
  ink: read("--ink", "#10221c"),
  fontDisplay: read("--font-display", '"Anek Latin", "Hind", system-ui, sans-serif'),
  forest: read("--forest", "#14624a"),
  sage: read("--sage", "#e8efea"),
  slate: read("--slate", "#5b6b64"),
  hairline: read("--hairline", "#e4e9e6"),
  indigo: read("--indigo", "#2e3a8c"),
  riskHigh: read("--risk-high", "#b3261e"),
  riskMedium: read("--risk-medium", "#8a5a00"),
};

/* Solid hairline, horizontal only. Recharts' default dashed cross-grid
   is the most recognisable "chart made from a template" tell there is,
   and vertical lines add nothing to a bar or area chart. */
export const gridProps = {
  stroke: TOKEN.hairline,
  vertical: false,
};

export const axisProps = {
  tick: { fontSize: 11, fill: TOKEN.slate },
  tickLine: false,
  axisLine: { stroke: TOKEN.hairline },
};

export const tooltipProps = {
  contentStyle: {
    border: `1px solid ${TOKEN.hairline}`,
    borderRadius: 6,
    boxShadow: "0 1px 3px rgba(16,34,28,0.08)",
    fontSize: 12.5,
    padding: "8px 12px",
  },
  labelStyle: { color: TOKEN.slate, fontSize: 11.5, marginBottom: 2 },
  itemStyle: { color: TOKEN.ink },
};

/* A figure printed on the mark itself.
 *
 * Ink, never the series colour. A red "38" beside a red bar says the
 * number is a category when it is a quantity, and it drags text below
 * the contrast the ink token guarantees. The colour belongs to the bar;
 * the number is text.
 *
 * Anek and tabular, so a column of figures lines up digit for digit --
 * the same treatment every other number in this product gets.
 *
 * Used selectively. A chart with a value over every one of fourteen
 * points is a table drawn badly; direct labels earn their place where
 * there are few enough marks that the axis can come off instead. */
export const valueLabelProps = {
  fill: TOKEN.ink,
  fontSize: 12,
  fontWeight: 600,
  fontFamily: TOKEN.fontDisplay,
};
