import 'package:flutter/material.dart';

import '../l10n/app_strings.dart';
import '../widgets/language_picker.dart';
import '../services/api_client.dart';
import '../services/offline_queue.dart';
import '../services/refresh_signal.dart';
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

  /// Shared by all three tabs -- see services/refresh_signal.dart. The
  /// IndexedStack below keeps every tab alive, so without this each one
  /// would show whatever it loaded at login for the rest of the session.
  final _refresh = RefreshSignal();

  static const _titleKeys = ['home', 'myPatients', 'followUps'];

  @override
  void initState() {
    super.initState();
    _queue = OfflineQueue();
    _syncService = SyncService(api: widget.api, queue: _queue, workerId: widget.session.workerId);
    // FR-01.3: auto-flush queued visits once online. A flush turns queued
    // audio into real visits on the server, so the tabs have to be told.
    _syncService.start(onFlushed: _onDataChanged);
    _refreshPending();
  }

  @override
  void dispose() {
    _refresh.dispose();
    super.dispose();
  }

  Future<void> _refreshPending() async {
    final count = await _queue.pendingCount(widget.session.workerId);
    if (mounted) setState(() => _pendingCount = count);
  }

  /// Something changed on the server: a visit was submitted, a queued one
  /// synced, a follow-up ticked off. Update the sync badge and tell every
  /// tab to refetch, so she never has to record the same visit twice just
  /// because the list still says "no visits recorded yet".
  void _onDataChanged() {
    _refreshPending();
    _refresh.ping();
  }

  Future<void> _syncNow() async {
    setState(() => _syncing = true);
    try {
      final result = await _syncService.flushNow();
      _onDataChanged();
      if (!mounted) return;
      final synced = result['synced'] as int? ?? 0;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            synced > 0 ? '${tr(context, 'synced')}: $synced' : tr(context, 'nothingToSync'),
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${tr(context, 'syncFailed')}: $e')),
      );
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  Future<void> _logout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(tr(context, 'signOutQuestion')),
        content: Text(tr(context, 'signOutBody')),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(tr(context, 'cancel')),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(tr(context, 'signOut')),
          ),
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
      HomeScreen(
        api: widget.api,
        session: widget.session,
        onVisitRecorded: _onDataChanged,
        refresh: _refresh,
      ),
      PatientListScreen(
        api: widget.api,
        workerId: widget.session.workerId,
        onVisitRecorded: _onDataChanged,
        refresh: _refresh,
      ),
      TaskListScreen(
        api: widget.api,
        workerId: widget.session.workerId,
        refresh: _refresh,
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: Text(tr(context, _titleKeys[_index])),
        actions: [
          const LanguagePicker(),
          IconButton(
            tooltip: _pendingCount > 0
                ? '$_pendingCount ${tr(context, 'waitingToSync')}'
                : tr(context, 'allSynced'),
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
          IconButton(
            onPressed: _logout,
            icon: const Icon(Icons.logout),
            tooltip: tr(context, 'signOut'),
          ),
        ],
      ),
      body: IndexedStack(index: _index, children: screens),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) {
          setState(() => _index = i);
          // Opening a tab reloads it. The stack never disposes a tab, so
          // this is the only moment it can be brought up to date.
          _onDataChanged();
        },
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.home_outlined),
            selectedIcon: const Icon(Icons.home),
            label: tr(context, 'home'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.people_outline),
            selectedIcon: const Icon(Icons.people),
            label: tr(context, 'myPatients'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.checklist_outlined),
            selectedIcon: const Icon(Icons.checklist),
            label: tr(context, 'followUps'),
          ),
        ],
      ),
    );
  }
}
