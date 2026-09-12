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

  Color get _color => switch (riskStatus) {
        'HIGH' => _high,
        'MEDIUM' => _medium,
        'LOW' => _low,
        _ => _unknown,
      };

  String get _label => switch (riskStatus) {
        'HIGH' => 'HIGH',
        'MEDIUM' => 'MED',
        'LOW' => 'LOW',
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
      label: riskStatus == null ? 'Risk not assessed' : '$riskStatus risk',
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
