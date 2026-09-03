import 'package:flutter/material.dart';

/// FR-07.2: RED / YELLOW / GREEN risk badges on the patient list.
class RiskBadge extends StatelessWidget {
  final String? riskStatus;

  const RiskBadge({super.key, this.riskStatus});

  Color get _color {
    switch (riskStatus) {
      case 'HIGH':
        return Colors.red;
      case 'MEDIUM':
        return Colors.amber.shade700;
      case 'LOW':
        return Colors.green;
      default:
        return Colors.grey;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 14,
      height: 14,
      decoration: BoxDecoration(color: _color, shape: BoxShape.circle),
    );
  }
}
