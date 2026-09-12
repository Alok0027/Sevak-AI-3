import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// The design tokens for every SevakAI surface.
///
/// Single source of truth: screens name tokens, never raw hex or raw
/// point sizes. That is what keeps the mobile app and the three web
/// dashboards reading as one product rather than four.
class T {
  T._();

  // ── Colour ────────────────────────────────────────────────────────
  // Five base values in one temperature. Every neutral carries a green
  // cast, so the brand doesn't float on generic grey.

  /// Near-black with a green cast. Primary text and headings.
  static const ink = Color(0xFF10221C);

  /// The brand green, deepened and cooled from the original #1F6F4A,
  /// which read yellow and muddied at small sizes. Identity and primary
  /// actions only.
  static const forest = Color(0xFF14624A);

  /// Pale green-grey. Selected rows and quiet fills.
  static const sage = Color(0xFFE8EFEA);

  /// The app background on every surface.
  static const paper = Color(0xFFF7F9F8);

  /// Muted text, metadata, and — deliberately — low risk.
  static const slate = Color(0xFF5B6B64);

  /// The one accent, and it carries meaning rather than decoration:
  /// indigo always marks *a person decided this* -- a risk override, a
  /// corrected transcript, an ASHA-edited vital, an audit entry. Forest
  /// marks what the system did. Applied strictly, that makes the line
  /// between AI output and human judgment readable everywhere without a
  /// legend; applied loosely it means nothing, so it appears nowhere
  /// else.
  static const indigo = Color(0xFF2E3A8C);

  static const surface = Colors.white;
  static const hairline = Color(0xFFE4E9E6);

  // ── Risk: instrumentation, not brand ──────────────────────────────
  // Low is grey on purpose. A green badge spends attention on the
  // patient who needs none; in a triage tool "fine" should be visually
  // silent. Amber is darkened to an ochre because the usual #D97706
  // fails AA at label sizes.

  static const riskHigh = Color(0xFFB3261E);
  static const riskMedium = Color(0xFF8A5A00);
  static const riskLow = slate;

  static Color risk(String? level) => switch (level) {
        'HIGH' => riskHigh,
        'MEDIUM' => riskMedium,
        _ => riskLow,
      };

  // ── Spacing (4pt base) ────────────────────────────────────────────
  static const s1 = 4.0;
  static const s2 = 8.0;
  static const s3 = 12.0;
  static const s4 = 16.0;
  static const s6 = 24.0;
  static const s8 = 32.0;
  static const s12 = 48.0;

  static const radius = 10.0;
  static const pill = 999.0;

  // ── Type ──────────────────────────────────────────────────────────
  // Hind for interface, Anek for display and figures. Both from Indian
  // Type Foundry, and Hind covers Latin *and* Devanagari in one family,
  // so Hindi and Marathi are drawn by the same hand at the same optical
  // weight as English rather than rendered in a fallback face. Tamil,
  // Telugu and Bengali have no Hind cut, so those scripts resolve
  // per-glyph to the phone's own Noto face -- correct and legible, just
  // not the same hand. Bundling script-specific cuts is the fix if the
  // mismatch ever shows in a demo.
  //
  // Loaded through google_fonts, which fetches once and caches. Each
  // call is guarded: if the font can't be resolved the app renders in
  // the platform face instead of failing to build a theme, which
  // matters on a first launch with no network.

  static TextStyle _hind(double size, FontWeight weight,
      {double? height, double? spacing, Color? color}) {
    final fallback = TextStyle(
      fontSize: size,
      fontWeight: weight,
      height: height,
      letterSpacing: spacing,
      color: color ?? ink,
    );
    try {
      return GoogleFonts.hind(textStyle: fallback);
    } catch (_) {
      return fallback;
    }
  }

  static TextStyle _anek(double size, FontWeight weight,
      {double? height, double? spacing, Color? color}) {
    final fallback = TextStyle(
      fontSize: size,
      fontWeight: weight,
      height: height,
      letterSpacing: spacing,
      color: color ?? ink,
      fontFeatures: const [FontFeature.tabularFigures()],
    );
    try {
      return GoogleFonts.getFont('Anek Latin', textStyle: fallback);
    } catch (_) {
      try {
        return GoogleFonts.hind(textStyle: fallback);
      } catch (_) {
        return fallback;
      }
    }
  }

  /// One per screen: the hero number or the greeting.
  static TextStyle get display => _anek(32, FontWeight.w600, height: 1.18, spacing: -0.4);

  static TextStyle get title => _anek(22, FontWeight.w600, height: 1.27);

  /// Figures, everywhere. Tabular so columns align.
  static TextStyle numeric(double size) => _anek(size, FontWeight.w600, height: 1.05);

  static TextStyle get section => _hind(17, FontWeight.w600, height: 1.41);
  static TextStyle get body => _hind(15, FontWeight.w400, height: 1.47);
  static TextStyle get strong => _hind(15, FontWeight.w600, height: 1.47);
  static TextStyle get caption => _hind(13, FontWeight.w500, height: 1.38, color: slate);

  /// Counts inside pills. Sentence case, never all-caps.
  static TextStyle get micro => _hind(11, FontWeight.w600, height: 1.45, spacing: 0.2);
}
