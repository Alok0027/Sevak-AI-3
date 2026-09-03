import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/history_models.dart';
import '../services/api_client.dart';
import '../services/session.dart';
import '../widgets/risk_badge.dart';
import '../widgets/stat_card.dart';
import 'patient_detail_screen.dart';

/// The ASHA worker's own "how am I doing" screen (FR-08 worker performance
/// metrics, scoped to just this worker). Every number here comes straight
/// from GET /workers/{worker_id}/history -- a real aggregate over her own
/// visits/patients/actions, never hardcoded.
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

  @override
  void initState() {
    super.initState();
    _historyFuture = widget.api.fetchWorkerHistory(widget.session.workerId);
  }

  Future<void> _refresh() async {
    final next = widget.api.fetchWorkerHistory(widget.session.workerId);
    setState(() => _historyFuture = next);
    await next;
  }

  String get _greeting {
    final hour = DateTime.now().hour;
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<WorkerHistory>(
        future: _historyFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return ListView(
              children: [
                const SizedBox(height: 100),
                Center(child: Text('Failed to load: ${snapshot.error}')),
              ],
            );
          }
          final data = snapshot.data!;
          final stats = data.worker;
          final recent = data.visits.take(5).toList();
          final firstName = stats.name.trim().isEmpty ? stats.name : stats.name.split(' ').first;

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text('$_greeting, $firstName',
                  style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
              Text(
                DateFormat.yMMMMEEEEd().format(DateTime.now()),
                style: TextStyle(color: Colors.grey.shade600),
              ),
              const SizedBox(height: 20),
              GridView.count(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisCount: 2,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 1.5,
                children: [
                  StatCard(
                    label: 'Patients Treated',
                    value: '${stats.totalPatients}',
                    icon: Icons.people,
                    color: const Color(0xFF2563EB),
                  ),
                  StatCard(
                    label: 'Total Visits',
                    value: '${stats.totalVisits}',
                    icon: Icons.fact_check,
                    color: const Color(0xFF1F6F4A),
                  ),
                  StatCard(
                    label: 'HIGH Risk Flags',
                    value: '${stats.highRiskCount}',
                    icon: Icons.warning_amber,
                    color: const Color(0xFFDC2626),
                  ),
                  StatCard(
                    label: 'Pending Follow-ups',
                    value: '${stats.pendingFollowups}',
                    icon: Icons.schedule,
                    color: const Color(0xFFD97706),
                  ),
                ],
              ),
              const SizedBox(height: 24),
              Text('Recent visits', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              if (recent.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Center(
                    child: Text('No visits recorded yet. Head to Patients to record your first one.'),
                  ),
                )
              else
                Card(
                  clipBehavior: Clip.antiAlias,
                  child: Column(
                    children: [
                      for (final v in recent)
                        ListTile(
                          leading: RiskBadge(riskStatus: v.riskLevel),
                          title: Text(v.patientName),
                          subtitle: Text(DateFormat.yMMMd().add_jm().format(v.createdAt)),
                          trailing: const Icon(Icons.chevron_right),
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
                ),
              const SizedBox(height: 12),
            ],
          );
        },
      ),
    );
  }
}
