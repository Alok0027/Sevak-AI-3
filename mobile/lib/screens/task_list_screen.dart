import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../services/api_client.dart';
import 'patient_detail_screen.dart';

/// FR-07.3: pending follow-ups sorted by urgency, with a checkbox to mark
/// one done straight from the app -- this is what feeds real completions
/// into the ANM/BMO "done vs pending" chart instead of a number that only
/// ever grows.
class TaskListScreen extends StatefulWidget {
  final ApiClient api;
  final String workerId;

  const TaskListScreen({super.key, required this.api, required this.workerId});

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
  }

  Future<void> _refresh() async {
    final next = widget.api.fetchTasks(widget.workerId);
    setState(() => _tasksFuture = next);
    await next;
  }

  Future<void> _complete(Map<String, dynamic> task) async {
    final actionId = task['action_id'] as String;
    setState(() => _completing.add(actionId));
    try {
      await widget.api.completeTask(actionId);
      await _refresh();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Marked done: ${task['patient_name']}')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed: $e')));
    } finally {
      if (mounted) setState(() => _completing.remove(actionId));
    }
  }

  Color _riskColor(String? level) {
    switch (level) {
      case 'HIGH':
        return Colors.red;
      case 'MEDIUM':
        return Colors.amber.shade700;
      default:
        return Colors.green;
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<List<Map<String, dynamic>>>(
        future: _tasksFuture,
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
          final tasks = snapshot.data ?? [];
          if (tasks.isEmpty) {
            return ListView(children: const [
              SizedBox(height: 100),
              Center(child: Text('No pending follow-ups. Great work!')),
            ]);
          }
          final now = DateTime.now();
          return ListView.separated(
            padding: const EdgeInsets.symmetric(vertical: 4),
            itemCount: tasks.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              final t = tasks[i];
              final actionId = t['action_id'] as String;
              final dueAt = t['due_at'] != null ? DateTime.parse(t['due_at'] as String) : null;
              final overdue = dueAt != null && dueAt.isBefore(now);
              final busy = _completing.contains(actionId);
              return ListTile(
                leading: CircleAvatar(backgroundColor: _riskColor(t['risk_level'] as String?), radius: 8),
                title: Text(t['patient_name'] as String),
                subtitle: Text(
                  '${t['content']}${dueAt != null ? '\nDue ${DateFormat.MMMd().add_jm().format(dueAt)}' : ''}',
                  style: overdue ? const TextStyle(color: Colors.red) : null,
                ),
                isThreeLine: dueAt != null,
                onTap: () {
                  final patientId = t['patient_id'] as String?;
                  if (patientId == null) return;
                  Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => PatientDetailScreen(api: widget.api, patientId: patientId),
                    ),
                  );
                },
                trailing: busy
                    ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                    : IconButton(
                        icon: const Icon(Icons.check_circle_outline),
                        tooltip: 'Mark done',
                        onPressed: () => _complete(t),
                      ),
              );
            },
          );
        },
      ),
    );
  }
}
