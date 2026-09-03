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

  SyncService({required this.api, required this.queue, required this.workerId});

  void start() {
    Connectivity().onConnectivityChanged.listen((results) async {
      final online = !results.contains(ConnectivityResult.none);
      if (online) {
        await flushNow();
      }
    });
  }

  Future<Map<String, dynamic>> flushNow() async {
    final unsynced = await queue.unsyncedRecords(workerId);
    if (unsynced.isEmpty) {
      return {'synced': 0, 'failed': 0};
    }
    final records = unsynced.map((row) => jsonDecode(row['record_json'] as String) as Map<String, dynamic>).toList();
    final result = await api.syncBatch(workerId, records);
    // Mark every queued row synced on success; a real implementation would
    // match response indices back to queue_ids for partial-failure handling.
    if ((result['failed'] as int? ?? 0) == 0) {
      for (final row in unsynced) {
        await queue.markSynced(row['queue_id'] as String);
      }
    }
    return result;
  }
}
