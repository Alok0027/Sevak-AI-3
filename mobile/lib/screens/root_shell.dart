import 'package:flutter/material.dart';

import '../l10n/app_strings.dart';
import '../widgets/language_picker.dart';
import '../widgets/tutorial_overlay.dart';
import '../services/api_client.dart';
import '../services/offline_queue.dart';
import '../services/refresh_signal.dart';
import '../services/patient_cache.dart';
import '../services/session.dart';
import '../services/sync_service.dart';
import '../theme/tokens.dart';
import 'help_screen.dart';
import 'home_screen.dart';
import 'login_screen.dart';
import 'patient_list_screen.dart';
import 'profile_screen.dart';
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

  /// What the first-run tour points at. They live on the shell because
  /// these are the three controls an ASHA has to find before the app is
  /// any use to her, and all three are in the shell's chrome rather than
  /// in a tab's body.
  final _patientsTabKey = GlobalKey();
  final _syncKey = GlobalKey();
  final _helpKey = GlobalKey();

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
    _maybeShowTutorial();
  }

  /// First sign-in on this phone, for this worker: show her round.
  ///
  /// After the first frame, because the tour measures the real controls to
  /// draw arrows at them and they do not have positions until they have
  /// been laid out.
  Future<void> _maybeShowTutorial() async {
    if (await TutorialPreference.hasSeen(widget.session.workerId)) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _runTutorial();
    });
  }

  Future<void> _runTutorial() async {
    // Marked seen when it starts, not when it finishes. She may well swipe
    // out of it or lose the app to a phone call; re-showing an uninvited
    // tour every single launch is how a helpful thing becomes an enemy.
    // Help has "Show me how to use the app" for anyone who wants it back.
    await TutorialPreference.markSeen(widget.session.workerId);
    if (!mounted) return;
    await showTutorial(context, [
      const TutorialStep(titleKey: 'tutWelcomeTitle', bodyKey: 'tutWelcomeBody'),
      TutorialStep(
        target: _patientsTabKey,
        titleKey: 'tutPatientsTitle',
        bodyKey: 'tutPatientsBody',
      ),
      // No target: the mic she is being told about lives on a patient row,
      // inside the tab she has just been shown, and pointing at a control
      // on a screen she is not looking at would be worse than saying it
      // plainly. This is the step that matters most -- speaking instead of
      // writing is the whole product.
      const TutorialStep(titleKey: 'tutRecordTitle', bodyKey: 'tutRecordBody'),
      TutorialStep(
        target: _syncKey,
        titleKey: 'tutSyncTitle',
        bodyKey: 'tutSyncBody',
        circular: true,
      ),
      TutorialStep(
        target: _helpKey,
        titleKey: 'tutHelpTitle',
        bodyKey: 'tutHelpBody',
        circular: true,
      ),
    ]);
  }

  void _openHelp() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => HelpScreen(api: widget.api, onReplayTutorial: _runTutorial),
      ),
    );
  }

  /// Profile carries sign-out as well as her code and her leave.
  ///
  /// Sign-out used to be its own icon up here, next to four others. On a
  /// 360dp phone that left "Follow-ups" ellipsised in the title, and the
  /// door icon sat one thumb-width from the sync button she is meant to
  /// tap often -- a bad pair to put side by side. It belongs with the
  /// rest of her account anyway.
  void _openProfile() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ProfileScreen(
          api: widget.api,
          // Cover changes whose patients her list contains, so every tab
          // has to refetch when she arranges or ends it.
          onChanged: _onDataChanged,
          onSignOut: _logout,
        ),
      ),
    );
  }

  @override
  void dispose() {
    _syncService.dispose();
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
    if (!mounted) return;
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
        SnackBar(content: Text('${tr(context, 'syncFailed')}: ${readableError(e)}')),
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
    await _syncService.dispose();
    await Session.clear();
    // Her saved patient list goes too. The unsent queue deliberately does
    // not (see OfflineQueue) -- work she recorded must survive a logout --
    // but a cached ward is just a copy of something the server can send
    // again, and it has no business staying on a handed-over handset.
    await PatientCache.clear();
    // The offline PIN goes with it. A signed-out phone must not still be
    // able to unlock her session without the server.
    await OfflineCredential.forget();
    widget.api.clearToken();
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
                    key: _syncKey,
                    label: Text('$_pendingCount'),
                    isLabelVisible: _pendingCount > 0,
                    child: Icon(_pendingCount > 0 ? Icons.cloud_off : Icons.cloud_done),
                  ),
          ),
          IconButton(
            key: _helpKey,
            onPressed: _openHelp,
            icon: const Icon(Icons.help_outline_rounded),
            tooltip: tr(context, 'help'),
          ),
          IconButton(
            onPressed: _openProfile,
            tooltip: tr(context, 'profile'),
            icon: CircleAvatar(
              radius: 14,
              backgroundColor: T.sage,
              child: Text(
                initialOf(widget.session.workerName),
                style: T.micro.copyWith(color: T.forest, fontSize: 13),
              ),
            ),
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
            key: _patientsTabKey,
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
