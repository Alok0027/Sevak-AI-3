import 'package:flutter/material.dart';

import '../theme/tokens.dart';

class Stat {
  final String value;
  final String label;
  const Stat(this.value, this.label);
}

/// Her four numbers as one divided strip rather than four floating
/// cards.
///
/// Four tinted cards read as four competing things and eat roughly a
/// third of the screen; one surface with hairline divisions says "this
/// is a single summary" and leaves the room for today's actual work,
/// which is what she opened the app for. Figures are Anek tabular, so
/// they sit on a common baseline and don't jitter as the counts change.
class StatStrip extends StatelessWidget {
  final List<Stat> stats;

  const StatStrip({super.key, required this.stats});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: T.surface,
        borderRadius: BorderRadius.circular(T.radius),
        border: Border.all(color: T.hairline),
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (var i = 0; i < stats.length; i++) ...[
              if (i > 0) const VerticalDivider(width: 1, thickness: 1, color: T.hairline),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: T.s2, vertical: T.s3),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerLeft,
                        child: Text(stats[i].value, style: T.numeric(24)),
                      ),
                      const SizedBox(height: T.s1),
                      Text(
                        stats[i].label,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: T.caption.copyWith(fontSize: 12, height: 1.25),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
