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
  String _subtitle(BuildContext context, Patient p) {
    final parts = <String>[
      if (p.age != null) '${p.age} ${tr(context, 'years')}',
      if (p.village != null && p.village!.isNotEmpty) p.village!,
    ];
    if (p.lastVisit != null) {
      parts.add('${p.totalVisits} ${tr(context, 'visits')}');
      parts.add('${tr(context, 'lastVisited')} ${DateFormat.MMMd().format(p.lastVisit!.toLocal())}');
    } else {
      parts.add(tr(context, 'noVisitsRecordedYet'));
    }
    return parts.join('  ·  ');
  }

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
                  return ListView(
                    padding: const EdgeInsets.fromLTRB(T.s4, T.s2, T.s4, 96),
                    children: [
                      StatusGroup(
                        children: [
                          for (final p in patients)
                            StatusRow(
                              railColour: T.risk(p.riskStatus),
                              // Her registered name, never translated.
                              title: p.name,
                              subtitle: _subtitle(context, p),
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
                            ),
                        ],
                      ),
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
