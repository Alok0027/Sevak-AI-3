import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../l10n/app_strings.dart';
import '../models/patient.dart';
import '../services/api_client.dart';
import '../services/refresh_signal.dart';
import '../theme/tokens.dart';
import '../widgets/status_group.dart';
import 'add_patient_screen.dart';
import 'patient_detail_screen.dart';
import 'voice_record_screen.dart';

/// FR-07.2: the ASHA's own patients, each row carrying its risk in the
/// leading rail rather than a badge. Tap a row for her full history; tap
/// the mic to go straight into recording a visit.
class PatientListScreen extends StatefulWidget {
  final ApiClient api;
  final String workerId;
  final VoidCallback? onVisitRecorded;

  /// Pinged by the shell whenever server state changes or this tab is
  /// opened. This screen lives inside an IndexedStack that never disposes
  /// it, so this is what keeps the list from being frozen at login.
  final RefreshSignal? refresh;

  const PatientListScreen({
    super.key,
    required this.api,
    required this.workerId,
    this.onVisitRecorded,
    this.refresh,
  });

  @override
  State<PatientListScreen> createState() => _PatientListScreenState();
}

class _PatientListScreenState extends State<PatientListScreen> {
  late Future<List<Patient>> _patientsFuture;
  String _search = '';

  @override
  void initState() {
    super.initState();
    _patientsFuture = widget.api.fetchPatients(widget.workerId);
    widget.refresh?.addListener(_refresh);
  }

  @override
  void dispose() {
    widget.refresh?.removeListener(_refresh);
    super.dispose();
  }

  Future<void> _refresh() async {
    if (!mounted) return;
    final next = widget.api.fetchPatients(widget.workerId);
    // Braces, not `=> _patientsFuture = next`: an arrow body *returns* the
    // assigned value, and Flutter asserts when a setState callback returns
    // a Future ("did you mean to await something in here?").
    setState(() {
      _patientsFuture = next;
    });
    try {
      await next;
    } catch (_) {
      // The FutureBuilder below shows the failure. Awaiting here is only
      // so the pull-to-refresh spinner stops when the request does -- and
      // swallowing it matters now that the signal calls this too: an ASHA
      // with no bars switching tabs would otherwise throw into no handler.
    }
  }

  Future<void> _recordVisit(Patient p) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => VoiceRecordScreen(api: widget.api, workerId: widget.workerId, patient: p),
      ),
    );
    // Fires the shared signal, which refreshes this list along with the
    // other tabs -- so one recording is enough, wherever it was made.
    widget.onVisitRecorded?.call();
    if (widget.refresh == null) _refresh();
  }

  Future<void> _addPatient() async {
    final created = await Navigator.of(context).push<Patient>(
      MaterialPageRoute(
        builder: (_) => AddPatientScreen(api: widget.api, workerId: widget.workerId),
      ),
    );
    if (created == null) return;
    await _refresh();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('${created.name} — ${tr(context, 'patientAdded')}'),
        action: SnackBarAction(
          label: tr(context, 'recordVisit'),
          textColor: Colors.white,
          onPressed: () => _recordVisit(created),
        ),
      ),
    );
  }

  /// "32 yrs · Wagholi · 4 visits · last 3 Sep" -- built from whatever is
  /// actually recorded, so a patient with only a name gets a short line
  /// rather than a line full of dashes.
  ///
  /// For a patient in today's work the reason comes first. She is reading
  /// this at a gate with a bag on her shoulder: "2d overdue" has to land
  /// before "32 yrs", because the age is context and the lateness is the
  /// instruction.
  String _subtitle(BuildContext context, Patient p) {
    final parts = <String>[
      if (p.needsAttention) _attention(context, p),
      if (p.age != null) '${p.age} ${tr(context, 'years')}',
      if (p.village != null && p.village!.isNotEmpty) p.village!,
    ];
    if (p.lastVisit != null) {
      parts.add('${p.totalVisits} ${tr(context, 'visits')}');
      parts.add('${tr(context, 'lastVisited')} ${DateFormat.MMMd().format(p.lastVisit!.toLocal())}');
    } else {
      parts.add(tr(context, 'noVisitsRecordedYet'));
    }
    return parts.where((s) => s.isNotEmpty).join('  ·  ');
  }

  /// Hours under a day, days above it -- the HIGH follow-up window is only
  /// 48 hours long, so rounding six hours late down to "0 days" would
  /// report a missed emergency as fine.
  String _attention(BuildContext context, Patient p) {
    switch (p.attentionReason) {
      case 'overdue':
        return p.hoursOverdue < 24
            ? tr(context, 'overdueHours').replaceAll('{n}', '${p.hoursOverdue}')
            : tr(context, 'overdueDays').replaceAll('{n}', '${p.hoursOverdue ~/ 24}');
      case 'due_today':
        return tr(context, 'dueTodayShort');
      case 'high_risk':
        return tr(context, 'highRiskShort');
      default:
        return '';
    }
  }

  StatusRow _row(BuildContext context, Patient p) => StatusRow(
        railColour: T.risk(p.riskStatus),
        // Her registered name, never translated.
        title: p.name,
        subtitle: _subtitle(context, p),
        // Colours the subtitle in the rail's own colour and gives it
        // weight. Deliberately the only extra emphasis an urgent row gets:
        // the rail already carries the colour, and a red pill on top of a
        // red rail beside red text is the same fact said three times.
        subtitleIsUrgent: p.needsAttention,
        // Only ever set while she is covering for someone on leave.
        //
        // A placeholder, not a prefix plus the name. In Hindi and Marathi
        // the phrase is a postposition -- "Sunita ke liye", not "ke liye
        // Sunita" -- so a string concatenated in English word order comes
        // out backwards in four of the six languages.
        note: p.coveringFor == null
            ? null
            : tr(context, 'coveringFor').replaceAll('{name}', p.coveringFor!),
        trailing: IconButton(
          icon: const Icon(Icons.mic, color: T.forest),
          tooltip: tr(context, 'recordAVisit'),
          onPressed: () => _recordVisit(p),
        ),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => PatientDetailScreen(
              api: widget.api,
              patientId: p.id,
              onVisitRecorded: widget.onVisitRecorded,
            ),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: T.forest,
        foregroundColor: Colors.white,
        onPressed: _addPatient,
        icon: const Icon(Icons.person_add_alt_1),
        label: Text(tr(context, 'addPatient'), style: T.strong.copyWith(color: Colors.white)),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, T.s2),
            child: TextField(
              style: T.body,
              decoration: InputDecoration(
                hintText: tr(context, 'searchPatients'),
                hintStyle: T.body.copyWith(color: T.slate.withValues(alpha: 0.8)),
                prefixIcon: const Icon(Icons.search, color: T.slate),
                isDense: true,
              ),
              onChanged: (v) => setState(() => _search = v.toLowerCase().trim()),
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              color: T.forest,
              onRefresh: _refresh,
              child: FutureBuilder<List<Patient>>(
                future: _patientsFuture,
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
                  final all = snapshot.data ?? [];
                  final patients = _search.isEmpty
                      ? all
                      : all.where((p) => p.name.toLowerCase().contains(_search)).toList();
                  if (patients.isEmpty) {
                    return ListView(
                      padding: const EdgeInsets.all(T.s4),
                      children: [
                        const SizedBox(height: T.s8),
                        Invitation(
                          icon: all.isEmpty ? Icons.person_add_alt_1 : Icons.search_off,
                          message: all.isEmpty
                              ? tr(context, 'noPatients')
                              : tr(context, 'noPatientsMatch'),
                        ),
                      ],
                    );
                  }
                  // The server has already ordered these worst-first. The
                  // list keeps that order rather than re-deciding it, so
                  // the ASHA and her ANM are never sorting the same ward
                  // two different ways.
                  final urgent = patients.where((p) => p.needsAttention).toList();
                  final rest = patients.where((p) => !p.needsAttention).toList();

                  return ListView(
                    padding: const EdgeInsets.fromLTRB(T.s4, T.s2, T.s4, 96),
                    children: urgent.isEmpty
                        // Nothing is urgent, so the screen says nothing.
                        //
                        // No "0 need attention" banner, no reassuring green
                        // card. A quiet screen on a calm day is the signal;
                        // a triage tool that decorates the absence of a
                        // problem teaches the reader to ignore its
                        // decorations, and then it has nothing left to say
                        // on the day somebody is actually in trouble.
                        ? [
                            StatusGroup(children: [for (final p in rest) _row(context, p)]),
                          ]
                        : [
                            SectionHeading(
                              tr(context, 'needsAttentionToday'),
                              trailing: '${urgent.length}',
                            ),
                            StatusGroup(children: [for (final p in urgent) _row(context, p)]),
                            if (rest.isNotEmpty) ...[
                              const SizedBox(height: T.s6),
                              SectionHeading(tr(context, 'everyoneElse')),
                              StatusGroup(children: [for (final p in rest) _row(context, p)]),
                            ],
                          ],
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}
