import 'dart:async';
import 'dart:convert';

import 'package:connectivity_plus/connectivity_plus.dart';

import 'api_client.dart';
import 'offline_queue.dart';

/// Watches connectivity and flushes the offline queue automatically
/// (FR-01.3: "successfully syncs and transcribes within 30 seconds of
/// connectivity"). Call [start] once after login.
class SyncService {
  final ApiClient api;
  final OfflineQueue queue;
  final String workerId;
  StreamSubscription<List<ConnectivityResult>>? _subscription;
  Future<Map<String, dynamic>>? _inFlight;
  bool _disposed = false;
  final Stream<List<ConnectivityResult>>? connectivityChanges;

  SyncService({required this.api, required this.queue, required this.workerId,
    this.connectivityChanges});

  /// [onFlushed] fires after a flush that actually pushed something, so the
  /// screens can refetch. Without it a visit recorded with no signal turns
  /// into a real server record silently, and the ASHA is left looking at a
  /// patient list that still shows her as never visited.
  void start({void Function()? onFlushed}) {
    if (_disposed || _subscription != null) return;
    _subscription = (connectivityChanges ?? Connectivity().onConnectivityChanged).listen((results) async {
      final online = !results.contains(ConnectivityResult.none);
      if (!online || _disposed) return;
      try {
        final result = await flushNow();
        if (!_disposed && (result['synced'] as int? ?? 0) > 0) {
          onFlushed?.call();
        }
      } catch (_) {
        // Keep pending data for the next manual/connectivity-triggered attempt.
      }
    }, onError: (Object _) {});
  }

  Future<void> dispose() async {
    _disposed = true;
    await _subscription?.cancel();
    _subscription = null;
  }

  Future<Map<String, dynamic>> flushNow() {
    if (_disposed) return Future.value({'synced': 0, 'failed': 0});
    return _inFlight ??= _flush().whenComplete(() => _inFlight = null);
  }

  Future<Map<String, dynamic>> _flush() async {
    // Snapshot IDs only, then load bounded batches of audio. Each queued item
    // is attempted at most once per flush, including permanently failing items.
    final ids = await queue.pendingIds(workerId);
    var synced = 0;
    var failed = 0;
    for (var offset = 0; offset < ids.length && !_disposed; offset += 20) {
      final end = offset + 20 < ids.length ? offset + 20 : ids.length;
      final unsynced = await queue.recordsByIds(workerId, ids.sublist(offset, end));
      if (_disposed || unsynced.isEmpty) continue;
      final records = unsynced.map((row) {
        final record = jsonDecode(row['record_json'] as String) as Map<String, dynamic>;
        if (record['record_type'] == 'visit') {
          record.putIfAbsent('client_request_id', () => row['queue_id']);
        }
        return record;
      }).toList();
      final result = await api.syncBatch(workerId, records);
      final acknowledgements = result['results'];
      final accepted = <int>{};
      if (acknowledgements is List) {
        for (final item in acknowledgements) {
          if (item is Map && item['status'] == 'synced' && item['index'] is int) {
            final index = item['index'] as int;
            if (index >= 0 && index < unsynced.length) accepted.add(index);
          }
        }
      } else if (result['failed'] == 0 && result['synced'] == unsynced.length) {
        // Compatibility with an older server: acknowledge only complete success.
        accepted.addAll(List.generate(unsynced.length, (index) => index));
      }
      for (final index in accepted) {
        await queue.markSynced(unsynced[index]['queue_id'] as String);
      }
      synced += accepted.length;
      failed += unsynced.length - accepted.length;
    }
    return {'synced': synced, 'failed': failed};
  }
}
