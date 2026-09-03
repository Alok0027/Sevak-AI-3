import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/patient.dart';
import '../services/api_client.dart';
import '../widgets/risk_badge.dart';
import 'add_patient_screen.dart';
import 'patient_detail_screen.dart';
import 'voice_record_screen.dart';

/// FR-07.2: worker's patient list with risk badges. Tap a patient to see
/// her full visit history; tap the mic to jump straight into recording a
/// new visit.
class PatientListScreen extends StatefulWidget {
  final ApiClient api;
  final String workerId;
  final VoidCallback? onVisitRecorded;

  const PatientListScreen({
    super.key,
    required this.api,
    required this.workerId,
    this.onVisitRecorded,
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
  }

  Future<void> _refresh() async {
    final next = widget.api.fetchPatients(widget.workerId);
    setState(() => _patientsFuture = next);
    await next;
  }

  Future<void> _recordVisit(Patient p) async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => VoiceRecordScreen(api: widget.api, workerId: widget.workerId, patient: p)),
    );
    widget.onVisitRecorded?.call();
    _refresh();
  }

  Future<void> _addPatient() async {
    final created = await Navigator.of(context).push<Patient>(
      MaterialPageRoute(builder: (_) => AddPatientScreen(api: widget.api)),
    );
    if (created == null) return;
    await _refresh();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('${created.name} added.'),
        action: SnackBarAction(label: 'Record visit', onPressed: () => _recordVisit(created)),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _addPatient,
        icon: const Icon(Icons.person_add),
        label: const Text('Add patient'),
      ),
      body: Column(
        children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: TextField(
            decoration: const InputDecoration(
              hintText: 'Search patients...',
              prefixIcon: Icon(Icons.search),
              border: OutlineInputBorder(),
              isDense: true,
            ),
            onChanged: (v) => setState(() => _search = v.toLowerCase().trim()),
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: _refresh,
            child: FutureBuilder<List<Patient>>(
              future: _patientsFuture,
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.waiting) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return ListView(children: [
                    const SizedBox(height: 100),
                    Center(child: Text('Failed to load: ${snapshot.error}')),
                  ]);
                }
                final all = snapshot.data ?? [];
                final patients =
                    _search.isEmpty ? all : all.where((p) => p.name.toLowerCase().contains(_search)).toList();
                if (patients.isEmpty) {
                  return ListView(children: [
                    const SizedBox(height: 100),
                    Center(
                      child: Text(
                        all.isEmpty
                            ? 'No patients yet. Tap "Add patient" below to register your first one.'
                            : 'No patients match "$_search".',
                      ),
                    ),
                  ]);
                }
                return ListView.separated(
                  itemCount: patients.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, i) {
                    final p = patients[i];
                    final subtitleParts = <String>[
                      if (p.age != null) '${p.age}y',
                      if (p.village != null) p.village!,
                    ];
                    final subtitle = p.lastVisit != null
                        ? '${subtitleParts.isNotEmpty ? '${subtitleParts.join(' · ')} · ' : ''}'
                            '${p.totalVisits} visit(s) · last ${DateFormat.yMMMd().format(p.lastVisit!)}'
                        : '${subtitleParts.isNotEmpty ? '${subtitleParts.join(' · ')} · ' : ''}No visits recorded yet';
                    return ListTile(
                      leading: RiskBadge(riskStatus: p.riskStatus),
                      title: Text(p.name),
                      subtitle: Text(subtitle),
                      trailing: IconButton(
                        icon: const Icon(Icons.mic),
                        tooltip: 'Record a visit',
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
                  },
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
