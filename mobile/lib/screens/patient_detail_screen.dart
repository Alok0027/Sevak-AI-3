import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/history_models.dart';
import '../models/patient.dart';
import '../services/api_client.dart';
import 'voice_record_screen.dart';

/// A patient's full visit timeline -- transcript + extracted structured
/// record for every past visit, sourced entirely from
/// GET /patients/{patient_id}/history (mirrors the dashboard's patient
/// detail page). Includes a shortcut to record a new visit for her.
class PatientDetailScreen extends StatefulWidget {
  final ApiClient api;
  final String patientId;
  final VoidCallback? onVisitRecorded;

  const PatientDetailScreen({
    super.key,
    required this.api,
    required this.patientId,
    this.onVisitRecorded,
  });

  @override
  State<PatientDetailScreen> createState() => _PatientDetailScreenState();
}

class _PatientDetailScreenState extends State<PatientDetailScreen> {
  late Future<PatientHistory> _future;
  int? _expandedIndex;

  @override
  void initState() {
    super.initState();
    _future = widget.api.fetchPatientHistory(widget.patientId);
  }

  Future<void> _refresh() async {
    final next = widget.api.fetchPatientHistory(widget.patientId);
    setState(() {
      _future = next;
      _expandedIndex = null;
    });
    await next;
  }

  Color _riskColor(String? level) {
    switch (level) {
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

  Future<void> _recordVisit(PatientHistory data) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => VoiceRecordScreen(
          api: widget.api,
          workerId: data.workerId,
          patient: Patient(id: data.patientId, name: data.patientName),
        ),
      ),
    );
    widget.onVisitRecorded?.call();
    _refresh();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Patient history')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<PatientHistory>(
          future: _future,
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
            final data = snapshot.data!;
            return ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
              children: [
                Row(
                  children: [
                    CircleAvatar(
                      radius: 28,
                      backgroundColor: const Color(0xFF1F6F4A),
                      child: Text(
                        data.patientName
                            .split(' ')
                            .where((p) => p.isNotEmpty)
                            .map((p) => p[0])
                            .take(2)
                            .join()
                            .toUpperCase(),
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18),
                      ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(data.patientName, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                          Text(
                            [
                              if (data.age != null) '${data.age} yrs',
                              if (data.village != null) data.village!,
                              if (data.pregnancyStage != null) '${data.pregnancyStage} pregnant',
                            ].join(' · '),
                            style: TextStyle(color: Colors.grey.shade600),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 20),
                Text('Visit timeline (${data.visits.length})', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                if (data.visits.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Center(child: Text('No visits recorded yet.')),
                  )
                else
                  for (int i = 0; i < data.visits.length; i++)
                    _VisitTile(
                      visit: data.visits[i],
                      color: _riskColor(data.visits[i].riskLevel),
                      expanded: _expandedIndex == i,
                      onTap: () => setState(() => _expandedIndex = _expandedIndex == i ? null : i),
                    ),
              ],
            );
          },
        ),
      ),
      floatingActionButton: FutureBuilder<PatientHistory>(
        future: _future,
        builder: (context, snapshot) {
          if (!snapshot.hasData) return const SizedBox.shrink();
          final data = snapshot.data!;
          return FloatingActionButton.extended(
            icon: const Icon(Icons.mic),
            label: const Text('Record visit'),
            onPressed: () => _recordVisit(data),
          );
        },
      ),
    );
  }
}

class _VisitTile extends StatelessWidget {
  final VisitEntry visit;
  final Color color;
  final bool expanded;
  final VoidCallback onTap;

  const _VisitTile({
    required this.visit,
    required this.color,
    required this.expanded,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final extracted = visit.extracted;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
                  const SizedBox(width: 8),
                  Expanded(child: Text(DateFormat.yMMMd().add_jm().format(visit.createdAt))),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(999)),
                    child: Text(
                      visit.riskLevel ?? '—',
                      style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold),
                    ),
                  ),
                ],
              ),
              if (visit.transcript != null && visit.transcript!.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    '"${visit.transcript}"',
                    style: TextStyle(fontStyle: FontStyle.italic, color: Colors.grey.shade700),
                  ),
                ),
              if (expanded && extracted != null) ...[
                const Divider(height: 20),
                for (final entry in extracted.entries)
                  if (entry.key != 'confidence_scores' &&
                      entry.value != null &&
                      entry.value.toString().isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          SizedBox(
                            width: 140,
                            child: Text(
                              entry.key.replaceAll('_', ' '),
                              style: TextStyle(color: Colors.grey.shade600, fontSize: 12),
                            ),
                          ),
                          Expanded(
                            child: Text(
                              entry.value is List ? (entry.value as List).join(', ') : entry.value.toString(),
                              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                            ),
                          ),
                        ],
                      ),
                    ),
              ],
              Align(
                alignment: Alignment.centerRight,
                child: Text(
                  expanded ? 'Tap to collapse' : 'Tap for full record',
                  style: TextStyle(fontSize: 11, color: Colors.grey.shade500),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
