import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../l10n/app_strings.dart';
import '../theme/tokens.dart';

/// A first-run walkthrough that points at the real controls.
///
/// Four steps, shown once, the first time an ASHA signs in. Not a carousel
/// of pictures: each step dims the screen except for one live control,
/// draws an arrow to it, and says in one sentence what it is for. She
/// finishes the tour looking at the app she is about to use rather than at
/// a slideshow of it.
///
/// The EOI deck claims "minimal training required" and names user adoption
/// as the top delivery risk. An ASHA is handed this app at a block meeting
/// with no manual; what she learns in the first two minutes is what she
/// will know a month later.
///
/// Deliberately small: four steps, skippable on every one, and replayable
/// from Help. A tour that cannot be escaped is worse than no tour, and an
/// ASHA who dismissed it on day one must be able to find it again on day
/// thirty.
class TutorialStep {
  /// The control this step is about. Null means a plain centred card --
  /// used for the welcome step, which is about the app rather than a
  /// button.
  final GlobalKey? target;
  final String titleKey;
  final String bodyKey;

  /// Circle rather than rounded rectangle, for round targets like the
  /// record button and the icons in the app bar.
  final bool circular;

  const TutorialStep({
    required this.titleKey,
    required this.bodyKey,
    this.target,
    this.circular = false,
  });
}

/// Remembers whether this worker has already seen the tour.
///
/// Keyed by worker_id, not a single global flag: an ASHA and her trainer
/// sometimes share a phone at a block meeting, and the second person to
/// sign in needs the tour as much as the first did.
class TutorialPreference {
  static String _key(String workerId) => 'tutorial_seen_$workerId';

  static Future<bool> hasSeen(String workerId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(_key(workerId)) ?? false;
    } catch (_) {
      // Storage unavailable: better to show the tour again than to
      // suppress it wrongly for somebody who has never seen it.
      return false;
    }
  }

  static Future<void> markSeen(String workerId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(_key(workerId), true);
    } catch (_) {
      // Not worth interrupting her for. Worst case she sees it twice.
    }
  }
}

/// Paints the dim layer with a hole cut out over the current target.
class _SpotlightPainter extends CustomPainter {
  final Rect? hole;
  final bool circular;

  _SpotlightPainter({required this.hole, required this.circular});

  @override
  void paint(Canvas canvas, Size size) {
    final scrim = Paint()..color = T.ink.withValues(alpha: 0.82);
    final full = Rect.fromLTWH(0, 0, size.width, size.height);

    if (hole == null) {
      canvas.drawRect(full, scrim);
      return;
    }

    // The cut-out, as a path with the hole subtracted -- one draw, so the
    // dim layer has no seam where two rectangles would have met.
    final padded = hole!.inflate(8);
    final holePath = Path();
    if (circular) {
      holePath.addOval(
        Rect.fromCircle(
          center: padded.center,
          radius: padded.longestSide / 2,
        ),
      );
    } else {
      holePath.addRRect(RRect.fromRectAndRadius(padded, const Radius.circular(T.radius)));
    }
    canvas.drawPath(
      Path.combine(PathOperation.difference, Path()..addRect(full), holePath),
      scrim,
    );

    // A ring on the target itself, so the highlighted control still reads
    // as highlighted on a screen bright enough to wash the scrim out.
    canvas.drawPath(
      holePath,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = Colors.white.withValues(alpha: 0.9),
    );
  }

  @override
  bool shouldRepaint(_SpotlightPainter old) =>
      old.hole != hole || old.circular != circular;
}

/// The arrow from the card to the highlighted control.
class _ArrowPainter extends CustomPainter {
  final Offset from;
  final Offset to;

  _ArrowPainter({required this.from, required this.to});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white
      ..strokeWidth = 2.5
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;

    // A slight curve rather than a straight line: it reads as a gesture
    // pointing at something, where a straight line reads as a divider.
    final control = Offset(
      (from.dx + to.dx) / 2 + (to.dy - from.dy) * 0.18,
      (from.dy + to.dy) / 2 + (from.dx - to.dx) * 0.18,
    );
    canvas.drawPath(
      Path()
        ..moveTo(from.dx, from.dy)
        ..quadraticBezierTo(control.dx, control.dy, to.dx, to.dy),
      paint,
    );

    // Head, aimed along the curve's final direction (from the control
    // point to the tip) rather than along the straight line, or it points
    // slightly wrong on the longer arrows.
    final direction = (to - control);
    final angle = direction.direction;
    const headLength = 13.0;
    const spread = 0.45;
    for (final sign in [1, -1]) {
      canvas.drawLine(
        to,
        to - Offset.fromDirection(angle + sign * spread, headLength),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(_ArrowPainter old) => old.from != from || old.to != to;
}

/// Shows [steps] as a full-screen coach-mark tour.
///
/// Returns when she finishes or skips. Safe to call with targets that are
/// not on screen: a step whose key has no box falls back to a centred
/// card, which is what happens if the layout changes and nobody updates
/// the tour.
Future<void> showTutorial(BuildContext context, List<TutorialStep> steps) {
  return Navigator.of(context, rootNavigator: true).push(
    PageRouteBuilder(
      opaque: false,
      barrierDismissible: false,
      // Just long enough to read as a deliberate arrival, short enough not
      // to be in the way on the third replay.
      transitionDuration: const Duration(milliseconds: 180),
      pageBuilder: (_, __, ___) => _TutorialView(steps: steps),
      transitionsBuilder: (_, animation, __, child) =>
          FadeTransition(opacity: animation, child: child),
    ),
  );
}

class _TutorialView extends StatefulWidget {
  final List<TutorialStep> steps;
  const _TutorialView({required this.steps});

  @override
  State<_TutorialView> createState() => _TutorialViewState();
}

class _TutorialViewState extends State<_TutorialView> {
  int _index = 0;

  Rect? _rectFor(TutorialStep step) {
    final context = step.target?.currentContext;
    if (context == null) return null;
    final box = context.findRenderObject() as RenderBox?;
    if (box == null || !box.hasSize) return null;
    return box.localToGlobal(Offset.zero) & box.size;
  }

  void _next() {
    if (_index + 1 < widget.steps.length) {
      setState(() => _index++);
    } else {
      Navigator.of(context).pop();
    }
  }

  Widget _card() => _TutorialCard(
        step: widget.steps[_index],
        index: _index,
        total: widget.steps.length,
        isLast: _index == widget.steps.length - 1,
        onNext: _next,
        onSkip: () => Navigator.of(context).pop(),
      );

  @override
  Widget build(BuildContext context) {
    final step = widget.steps[_index];
    final rect = _rectFor(step);
    final screen = MediaQuery.of(context).size;

    // Put the card on the opposite side of the screen from the target, so
    // the thing she is being told about is never behind the thing telling
    // her about it.
    final targetIsLow = rect != null && rect.center.dy > screen.height / 2;
    final cardTop = rect == null
        ? null
        : (targetIsLow ? screen.height * 0.16 : rect.bottom + 72);

    return Material(
      type: MaterialType.transparency,
      child: Stack(
        children: [
          Positioned.fill(
            child: CustomPaint(
              painter: _SpotlightPainter(hole: rect, circular: step.circular),
            ),
          ),
          if (rect != null)
            Positioned.fill(
              child: IgnorePointer(
                child: CustomPaint(
                  painter: _ArrowPainter(
                    // Starts at the card's edge nearest the target and ends
                    // just short of it, so the head sits beside the control
                    // rather than on top of it.
                    from: Offset(
                      screen.width / 2,
                      targetIsLow ? screen.height * 0.16 + 150 : rect.bottom + 64,
                    ),
                    to: Offset(
                      rect.center.dx,
                      targetIsLow ? rect.top - 16 : rect.bottom + 16,
                    ),
                  ),
                ),
              ),
            ),
          if (rect != null)
            Positioned(
              left: T.s4,
              right: T.s4,
              top: cardTop,
              child: _card(),
            )
          else
            Center(child: Padding(padding: const EdgeInsets.all(T.s4), child: _card())),
        ],
      ),
    );
  }
}

class _TutorialCard extends StatelessWidget {
  final TutorialStep step;
  final int index;
  final int total;
  final bool isLast;
  final VoidCallback onNext;
  final VoidCallback onSkip;

  const _TutorialCard({
    required this.step,
    required this.index,
    required this.total,
    required this.isLast,
    required this.onNext,
    required this.onSkip,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(T.s4),
      decoration: BoxDecoration(
        color: T.surface,
        borderRadius: BorderRadius.circular(T.radius),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${index + 1} ${tr(context, 'tutStepOf')} $total',
            style: T.micro.copyWith(color: T.forest),
          ),
          const SizedBox(height: T.s2),
          Text(tr(context, step.titleKey), style: T.title),
          const SizedBox(height: T.s2),
          Text(tr(context, step.bodyKey), style: T.body.copyWith(color: T.slate)),
          const SizedBox(height: T.s4),
          Row(
            children: [
              // Skip stays on every step, including the last. A tour you
              // cannot leave is worse than no tour.
              TextButton(
                onPressed: onSkip,
                child: Text(tr(context, 'tutSkip'), style: T.body.copyWith(color: T.slate)),
              ),
              const Spacer(),
              FilledButton(
                // The app theme gives FilledButton minimumSize
                // Size.fromHeight(52), whose width is double.infinity. A Row
                // lays a non-flexible child out with unbounded width, so that
                // minimum survives and the button asks for infinite size --
                // a layout exception, not a squashed button. Same override
                // patient_detail_screen.dart uses for the same reason.
                style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
                onPressed: onNext,
                child: Text(tr(context, isLast ? 'tutDone' : 'tutNext')),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
