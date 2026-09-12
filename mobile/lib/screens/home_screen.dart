import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../l10n/app_strings.dart';
import '../models/history_models.dart';
import '../services/api_client.dart';
import '../services/session.dart';
import '../theme/tokens.dart';
import '../widgets/stat_strip.dart';
import '../widgets/status_group.dart';
import 'patient_detail_screen.dart';

/// The ASHA's opening screen: the day, then the person.
///
/// Ordered by what she came here to find out. Greeting and date first,
/// because she often opens this between houses and needs to know where
/// she is in the day. Her own numbers next, as a quiet strip rather than
/// a wall of tiles. Then today's visits, above her recent history --
/// what is still owed matters more than what is already done.
///
/// Every figure here is a real aggregate the backend computed from her
/// own visit and action rows. Nothing on this screen is illustrative.
class HomeScreen extends StatefulWidget {
  final ApiClient api;
  final Session session;
  final VoidCallback? onVisitRecorded;

  const HomeScreen({super.key, required this.api, required this.session, this.onVisitRecorded});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<WorkerHistory> _historyFuture;
  Key _todayKey = UniqueKey();

  @override
  void initState() {
    super.initState();
    _historyFuture = widget.api.fetchWorkerHistory(widget.session.workerId);
  }

  Future<void> _refresh() async {
    final next = widget.api.fetchWorkerHistory(widget.session.workerId);
    setState(() {
      _historyFuture = next;
      _todayKey = UniqueKey(); // re-fetches today's list against the server too
    });
    await next;
  }

  String _greeting(BuildContext context) {
    final hour = DateTime.now().hour;
    if (hour < 12) return tr(context, 'goodMorning');
    if (hour < 17) return tr(context, 'goodAfternoon');
    return tr(context, 'goodEvening');
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      color: T.forest,
      onRefresh: _refresh,
      child: FutureBuilder<WorkerHistory>(
        future: _historyFuture,
        builder: (context, snapshot) {
          final loading = snapshot.connectionState == ConnectionState.waiting;
          final data = snapshot.data;
          final firstName = data == null ? '' : data.worker.name.trim().split(' ').first;

          return ListView(
            padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, T.s8),
            children: [
              Text(
                data == null ? _greeting(context) : '${_greeting(context)}, $firstName',
                style: T.display,
              ),
              const SizedBox(height: T.s1),
              Text(DateFormat.yMMMMEEEEd().format(DateTime.now()), style: T.caption),
              const SizedBox(height: T.s6),
              if (loading)
                const LinearProgressIndicator(minHeight: 2)
              else if (snapshot.hasError)
                Invitation(
                  icon: Icons.wifi_off_rounded,
                  message: tr(context, 'statsNeedConnection'),
                )
              else
                StatStrip(
                  stats: [
                    Stat('${data!.worker.totalPatients}', tr(context, 'patientsTreated')),
                    Stat('${data.worker.totalVisits}', tr(context, 'totalVisits')),
                    Stat('${data.worker.highRiskCount}', tr(context, 'highRiskFlags')),
                    Stat('${data.worker.pendingFollowups}', tr(context, 'pendingFollowups')),
                  ],
                ),
              const SizedBox(height: T.s6),
              _TodayVisits(
                key: _todayKey,
                api: widget.api,
                workerId: widget.session.workerId,
                onVisitRecorded: widget.onVisitRecorded,
              ),
              if (data != null) ...[
                const SizedBox(height: T.s6),
                SectionHeading(tr(context, 'recentVisits')),
                if (data.visits.isEmpty)
                  Invitation(icon: Icons.mic_none_rounded, message: tr(context, 'noVisitsYet'))
                else
                  StatusGroup(
                    children: [
                      for (final v in data.visits.take(5))
                        StatusRow(
                          railColour: T.risk(v.riskLevel),
                          title: v.patientName,
                          subtitle: DateFormat.yMMMd().add_jm().format(v.createdAt),
                          trailing: const Icon(Icons.chevron_right, size: 20, color: T.slate),
                          onTap: () => Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => PatientDetailScreen(
                                api: widget.api,
                                patientId: v.patientId,
                                onVisitRecorded: widget.onVisitRecorded,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}

/// FR-07.3, her answer to "who am I seeing today?".
///
/// Today's work is the overdue visits plus the ones due today, in that
/// order -- a mother whose 48-hour follow-up lapsed yesterday is more
/// today's problem than one due this evening. The buckets come from the
/// server, the same source her supervisor's dashboard reads, so the two
/// can never disagree about whether she is behind.
///
/// Loads separately from the stats above, so a failure here costs one
/// line rather than the whole screen.
class _TodayVisits extends StatefulWidget {
  final ApiClient api;
  final String workerId;
  final VoidCallback? onVisitRecorded;

  const _TodayVisits({super.key, required this.api, required this.workerId, this.onVisitRecorded});

  @override
  State<_TodayVisits> createState() => _TodayVisitsState();
}

class _TodayVisitsState extends State<_TodayVisits> {
  late final Future<Map<String, dynamic>> _boardFuture =
      widget.api.fetchTaskBoard(widget.workerId);

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Map<String, dynamic>>(
      future: _boardFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeading(tr(context, 'todaysVisits')),
              const LinearProgressIndicator(minHeight: 2),
            ],
          );
        }
        if (snapshot.hasError) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeading(tr(context, 'todaysVisits')),
              Invitation(
                icon: Icons.wifi_off_rounded,
                message: tr(context, 'todayNeedsConnection'),
              ),
            ],
          );
        }

        final board = snapshot.data!;
        final today = (board['today'] as List).cast<Map<String, dynamic>>();
        final summary = (board['summary'] as Map).cast<String, dynamic>();
        final overdue = (summary['overdue'] as int?) ?? 0;

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeading(
              tr(context, 'todaysVisits'),
              trailing: today.isEmpty ? null : '${today.length} ${tr(context, 'toSee')}',
            ),
            if (today.isEmpty)
              Invitation(icon: Icons.check_circle_outline, message: tr(context, 'nothingDueToday'))
            else ...[
              if (overdue > 0) ...[
                Text(
                  overdue == 1
                      ? tr(context, 'onePastDue')
                      : '$overdue ${tr(context, 'manyPastDue')}',
                  style: T.caption.copyWith(color: T.riskHigh, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: T.s2),
              ],
              StatusGroup(
                children: [
                  for (final t in today)
                    StatusRow(
                      railColour: T.risk(t['risk_level'] as String?),
                      title: t['patient_name'] as String,
                      subtitle: _rowSubtitle(context, t),
                      subtitleIsUrgent: t['bucket'] == 'overdue',
                      trailing: const Icon(Icons.chevron_right, size: 20, color: T.slate),
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => PatientDetailScreen(
                            api: widget.api,
                            patientId: t['patient_id'] as String,
                            onVisitRecorded: widget.onVisitRecorded,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ],
          ],
        );
      },
    );
  }
}

String _rowSubtitle(BuildContext context, Map<String, dynamic> task) {
  final village = task['village'] as String?;
  final parts = <String>[
    if (village != null && village.isNotEmpty) village,
    _localisedDue(context, task),
  ];
  // The server collapses today's list to one row per person and tells us
  // how many other follow-ups are waiting at the same door. Say so rather
  // than dropping them silently -- she should know the visit has more
  // than one reason before she knocks.
  final alsoPending = (task['also_pending'] as int?) ?? 0;
  if (alsoPending > 0) parts.add('+$alsoPending ${tr(context, 'moreDueHere')}');
  return parts.join('  ·  ');
}

/// The server sends a ready-made label ("3d overdue") but in English --
/// it has no idea which language the app is showing. It also sends the
/// raw bucket and hour count, so rebuild the phrase here and the screen
/// stays in one language throughout. Falls back to the server's wording
/// if that shape ever changes.
String _localisedDue(BuildContext context, Map<String, dynamic> task) {
  final bucket = task['bucket'] as String?;
  final hours = (task['hours_overdue'] as int?) ?? 0;
  switch (bucket) {
    case 'overdue':
      return hours < 24
          ? '$hours${tr(context, 'hoursOverdue')}'
          : '${hours ~/ 24}${tr(context, 'daysOverdue')}';
    case 'due_today':
      return tr(context, 'dueToday');
    case 'upcoming':
      return tr(context, 'upcoming');
    case 'unscheduled':
      return tr(context, 'noDateSet');
    default:
      return (task['label'] as String?) ?? '';
  }
}
