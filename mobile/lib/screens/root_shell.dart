import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../services/offline_queue.dart';
import '../services/session.dart';
import '../services/sync_service.dart';
import 'home_screen.dart';
import 'login_screen.dart';
import 'patient_list_screen.dart';
import 'task_list_screen.dart';

/// Bottom-nav shell wrapping the ASHA worker's three main screens, plus a
/// sync-status affordance in the AppBar. FR-01.3/FR-07.1: the offline queue
/// flushes automatically once connectivity returns; the cloud icon shows
/// how many visits are still waiting and lets her trigger a sync by hand.
class RootShell extends StatefulWidget {
  final ApiClient api;
  final Session session;

  const RootShell({super.key, required this.api, required this.session});

  @override
  State<RootShell> createState() => _RootShellState();
}

class _RootShellState extends State<RootShell> {
  int _index = 0;
  late final OfflineQueue _queue;
  late final SyncService _syncService;
  int _pendingCount = 0;
  bool _syncing = false;

  static const _titles = ['Home', 'My Patients', 'Follow-ups'];

  @override
  void initState() {
    super.initState();
    _queue = OfflineQueue();
    _syncService = SyncService(api: widget.api, queue: _queue, workerId: widget.session.workerId);
    _syncService.start(); // FR-01.3: auto-flush queued visits once online
    _refreshPending();
  }

  Future<void> _refreshPending() async {
    final count = await _queue.pendingCount(widget.session.workerId);
    if (mounted) setState(() => _pendingCount = count);
  }

  Future<void> _syncNow() async {
    setState(() => _syncing = true);
    try {
      final result = await _syncService.flushNow();
      await _refreshPending();
      if (!mounted) return;
      final synced = result['synced'] as int? ?? 0;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(synced > 0 ? 'Synced $synced visit(s).' : 'Nothing to sync yet.')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Sync failed: $e')),
      );
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  Future<void> _logout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text('You will need your phone number and PIN to sign in again.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Sign out')),
        ],
      ),
    );
    if (confirmed != true) return;
    await Session.clear();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => LoginScreen(api: widget.api)),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      HomeScreen(api: widget.api, session: widget.session, onVisitRecorded: _refreshPending),
      PatientListScreen(
        api: widget.api,
        workerId: widget.session.workerId,
        onVisitRecorded: _refreshPending,
      ),
      TaskListScreen(api: widget.api, workerId: widget.session.workerId),
    ];

    return Scaffold(
      appBar: AppBar(
        title: Text(_titles[_index]),
        actions: [
          IconButton(
            tooltip: _pendingCount > 0 ? '$_pendingCount visit(s) waiting to sync' : 'All synced',
            onPressed: (_pendingCount > 0 && !_syncing) ? _syncNow : null,
            icon: _syncing
                ? const SizedBox(
                    width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : Badge(
                    label: Text('$_pendingCount'),
                    isLabelVisible: _pendingCount > 0,
                    child: Icon(_pendingCount > 0 ? Icons.cloud_off : Icons.cloud_done),
                  ),
          ),
          IconButton(onPressed: _logout, icon: const Icon(Icons.logout), tooltip: 'Sign out'),
        ],
      ),
      body: IndexedStack(index: _index, children: screens),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) {
          setState(() => _index = i);
          _refreshPending();
        },
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'Home'),
          NavigationDestination(
            icon: Icon(Icons.people_outline), selectedIcon: Icon(Icons.people), label: 'Patients'),
          NavigationDestination(
            icon: Icon(Icons.checklist_outlined), selectedIcon: Icon(Icons.checklist), label: 'Tasks'),
        ],
      ),
    );
  }
}
