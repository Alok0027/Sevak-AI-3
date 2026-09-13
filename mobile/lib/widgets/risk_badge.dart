import 'package:flutter/material.dart';

/// FR-07.2: the risk marker on patient lists and task rows.
///
/// Labelled rather than a bare coloured dot. Colour alone is the wrong
/// carrier here for two reasons that both apply to this app: roughly one
/// man in twelve has a red/green deficiency, and an ASHA reads this on a
/// mid-range screen in daylight, where a small saturated dot washes out.
/// The word survives both. [compact] keeps the old dot for dense rows
/// where a pill would crowd the layout.
class RiskBadge extends StatelessWidget {
  final String? riskStatus;
  final bool compact;

  const RiskBadge({super.key, this.riskStatus, this.compact = false});

  // Deeper than the Material defaults: amber.shade700 on white fails
  // contrast at this text size, and these are read outdoors.
  static const _high = Color(0xFFDC2626);
  static const _medium = Color(0xFFB45309);
  static const _low = Color(0xFF15803D);
  static const _unknown = Color(0xFF6B7280);

  // Not a fourth severity. UNASSESSED means the visit produced nothing
  // the classifier could score -- the recording failed, or nothing in it
  // was a vital sign. It takes the amber of MEDIUM rather than the grey
  // of _unknown, because grey reads as "nothing to see" and this is the
  // one badge on the screen that asks the ASHA to go back and redo
  // something. It is not red: nobody is in danger as far as we know, and
  // that is exactly the problem.
  static const _unassessed = _medium;

  Color get _color => switch (riskStatus) {
        'HIGH' => _high,
        'MEDIUM' => _medium,
        'LOW' => _low,
        'UNASSESSED' => _unassessed,
        _ => _unknown,
      };

  String get _label => switch (riskStatus) {
        'HIGH' => 'HIGH',
        'MEDIUM' => 'MED',
        'LOW' => 'LOW',
        'UNASSESSED' => 'RECHECK',
        _ => '—',
      };

  @override
  Widget build(BuildContext context) {
    if (compact) {
      return Container(
        width: 12,
        height: 12,
        decoration: BoxDecoration(
          color: _color,
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 1.5),
          boxShadow: [BoxShadow(color: _color.withValues(alpha: 0.35), blurRadius: 4)],
        ),
      );
    }

    return Semantics(
      label: switch (riskStatus) {
        null => 'Risk not assessed',
        // Screen readers would otherwise announce "UNASSESSED risk",
        // which parses as a severity. This is not one.
        'UNASSESSED' => 'Not assessed, needs recording again',
        _ => '$riskStatus risk',
      },
      child: Container(
        constraints: const BoxConstraints(minWidth: 52),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: _color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: _color.withValues(alpha: 0.30)),
        ),
        child: Text(
          _label,
          textAlign: TextAlign.center,
          style: TextStyle(
            color: _color,
            fontSize: 11,
            fontWeight: FontWeight.w800,
            letterSpacing: 0.4,
          ),
        ),
      ),
    );
  }
}
