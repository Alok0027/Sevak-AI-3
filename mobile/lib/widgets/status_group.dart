import 'package:flutter/material.dart';

import '../theme/tokens.dart';

/// The recurring form across every SevakAI surface.
///
/// Related rows share one grouped surface separated by a light divider,
/// and each row carries a 3px bar on its leading edge in its risk
/// colour. Read top to bottom it becomes a single spine of urgency you
/// can scan in one pass.
///
/// Chosen over giving every row its own rounded, shadowed card for two
/// reasons: a column of identical floating cards is the default look of
/// every dashboard kit and says nothing about this product, and the
/// padding each one needs costs roughly a third of the rows that fit on
/// an ASHA's screen. The rail keeps the density a district officer needs
/// while staying legible one-handed in sunlight.
class StatusGroup extends StatelessWidget {
  final List<Widget> children;

  const StatusGroup({super.key, required this.children});

  @override
  Widget build(BuildContext context) {
    if (children.isEmpty) return const SizedBox.shrink();
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: T.surface,
        borderRadius: BorderRadius.circular(T.radius),
        border: Border.all(color: T.hairline),
      ),
      child: Column(
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) const Divider(height: 1, thickness: 1, color: T.hairline),
            children[i],
          ],
        ],
      ),
    );
  }
}

/// One row inside a [StatusGroup].
///
/// [railColour] is the whole point — pass the risk colour, and low risk
/// resolves to slate so a settled patient stays visually quiet.
class StatusRow extends StatelessWidget {
  final Color railColour;
  final String title;
  final String? subtitle;

  /// Emphasises the subtitle, for rows where the status is the news --
  /// an overdue visit rather than a routine one.
  final bool subtitleIsUrgent;
  final Widget? trailing;
  final VoidCallback? onTap;

  const StatusRow({
    super.key,
    required this.railColour,
    required this.title,
    this.subtitle,
    this.subtitleIsUrgent = false,
    this.trailing,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: onTap != null,
      child: InkWell(
        onTap: onTap,
        child: IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(width: 3, color: railColour),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(T.s4, T.s3, T.s3, T.s3),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(title, style: T.strong),
                            if (subtitle != null) ...[
                              const SizedBox(height: 2),
                              Text(
                                subtitle!,
                                style: T.caption.copyWith(
                                  color: subtitleIsUrgent ? railColour : T.slate,
                                  fontWeight:
                                      subtitleIsUrgent ? FontWeight.w600 : FontWeight.w500,
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                      if (trailing != null) ...[const SizedBox(width: T.s2), trailing!],
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// A heading above a group, with an optional count on the right.
class SectionHeading extends StatelessWidget {
  final String label;
  final String? trailing;

  const SectionHeading(this.label, {super.key, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: T.s2),
      child: Row(
        children: [
          Expanded(child: Text(label, style: T.section)),
          if (trailing != null) Text(trailing!, style: T.caption),
        ],
      ),
    );
  }
}

/// An empty state that invites the next action instead of reporting
/// absence. Never apologises, never says "no data".
class Invitation extends StatelessWidget {
  final IconData icon;
  final String message;

  const Invitation({super.key, required this.icon, required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(T.s4),
      decoration: BoxDecoration(
        color: T.sage,
        borderRadius: BorderRadius.circular(T.radius),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: T.forest),
          const SizedBox(width: T.s3),
          Expanded(child: Text(message, style: T.body.copyWith(color: T.ink))),
        ],
      ),
    );
  }
}
