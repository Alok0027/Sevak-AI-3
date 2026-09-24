import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../l10n/app_strings.dart';
import '../services/api_client.dart';
import '../services/refresh_signal.dart';
import '../theme/tokens.dart';
import '../widgets/status_group.dart';
import 'patient_detail_screen.dart';

/// FR-07.3: every pending follow-up, soonest due first, with one tap to
/// mark it done. This is what feeds real completions into the ANM/BMO
/// "done vs pending" chart instead of a number that only ever grows.
///
/// Unlike the home screen's today list — which is collapsed to one row
/// per person, because she walks to a house rather than to an action —
/// this list stays one row per follow-up. It is the place where an
/// individual task gets ticked off, so each one has to be addressable.
class TaskListScreen extends StatefulWidget {
  final ApiClient api;
  final String workerId;

  /// Pinged by the shell when server state changes or this tab is opened.
  /// A HIGH visit recorded a minute ago generates the follow-ups that show
  /// up here, so this list has to reload rather than sit at its login state.
  final RefreshSignal? refresh;

  const TaskListScreen({
    super.key,
    required this.api,
    required this.workerId,
    this.refresh,
  });

  @override
  State<TaskListScreen> createState() => _TaskListScreenState();
}

class _TaskListScreenState extends State<TaskListScreen> {
  late Future<List<Map<String, dynamic>>> _tasksFuture;
  final Set<String> _completing = {};

  @override
  void initState() {
    super.initState();
    _tasksFuture = widget.api.fetchTasks(widget.workerId);
    widget.refresh?.addListener(_refresh);
  }

  @override
  void dispose() {
    widget.refresh?.removeListener(_refresh);
    super.dispose();
  }

  Future<void> _refresh() async {
    if (!mounted) return;
    final next = widget.api.fetchTasks(widget.workerId);
    // Braces, not an arrow body -- see patient_list_screen.dart: an arrow
    // returns the assigned Future and Flutter asserts on that.
    setState(() {
      _tasksFuture = next;
    });
    try {
      await next;
    } catch (_) {
      // Shown by the FutureBuilder; see patient_list_screen.dart.
    }
  }

  Future<void> _complete(Map<String, dynamic> task) async {
    final actionId = task['action_id'] as String;
    setState(() => _completing.add(actionId));
    try {
      await widget.api.completeTask(actionId);
      await _refresh();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${tr(context, 'markedDone')}: ${task['patient_name']}')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${tr(context, 'failed')}: ${readableError(e)}')),
      );
    } finally {
      if (mounted) setState(() => _completing.remove(actionId));
    }
  }

  /// What the follow-up is and when it's owed, in her language. The server
  /// sends a ready-made English label alongside the raw bucket and hour
  /// count; rebuild the phrase here so the row never mixes two languages.
  String _subtitle(BuildContext context, Map<String, dynamic> t) {
    final content = (t['content'] as String?)?.trim();
    final bucket = t['bucket'] as String?;
    final hours = (t['hours_overdue'] as int?) ?? 0;
    final due = t['due_at'] != null ? DateTime.parse(t['due_at'] as String).toLocal() : null;

    final when = switch (bucket) {
      'overdue' => hours < 24
          ? '$hours${tr(context, 'hoursOverdue')}'
          : '${hours ~/ 24}${tr(context, 'daysOverdue')}',
      'due_today' => tr(context, 'dueToday'),
      'upcoming' => due != null
          ? '${tr(context, 'due')} ${DateFormat.MMMd().format(due)}'
          : tr(context, 'upcoming'),
      _ => tr(context, 'noDateSet'),
    };
    return (content == null || content.isEmpty) ? when : '$content  ·  $when';
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      color: T.forest,
      onRefresh: _refresh,
      child: FutureBuilder<List<Map<String, dynamic>>>(
        future: _tasksFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator(color: T.forest));
          }
          if (snapshot.hasError) {
            return ListView(
              padding: const EdgeInsets.all(T.s4),
              children: [
                const SizedBox(height: T.s8),
                Invitation(
                  icon: Icons.wifi_off_rounded,
                  message: '${tr(context, 'failedToLoad')}: ${snapshot.error}',
                ),
              ],
            );
          }
          final tasks = snapshot.data ?? [];
          if (tasks.isEmpty) {
            return ListView(
              padding: const EdgeInsets.all(T.s4),
              children: [
                const SizedBox(height: T.s8),
                Invitation(
                  icon: Icons.check_circle_outline,
                  message: tr(context, 'noFollowUps'),
                ),
              ],
            );
          }
          return ListView(
            padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, T.s8),
            children: [
              StatusGroup(
                children: [
                  for (final t in tasks)
                    StatusRow(
                      railColour: T.risk(t['risk_level'] as String?),
                      // Her registered name, never translated.
                      title: t['patient_name'] as String,
                      subtitle: _subtitle(context, t),
                      subtitleIsUrgent: t['bucket'] == 'overdue',
                      trailing: _completing.contains(t['action_id'])
                          ? const SizedBox(
                              width: 24,
                              height: 24,
                              child: CircularProgressIndicator(strokeWidth: 2, color: T.forest),
                            )
                          : IconButton(
                              icon: const Icon(Icons.check_circle_outline, color: T.forest),
                              tooltip: tr(context, 'markDone'),
                              onPressed: () => _complete(t),
                            ),
                      onTap: () {
                        final patientId = t['patient_id'] as String?;
                        if (patientId == null) return;
                        Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) =>
                                PatientDetailScreen(api: widget.api, patientId: patientId),
                          ),
                        );
                      },
                    ),
                ],
              ),
            ],
          );
        },
      ),
    );
  }
}
