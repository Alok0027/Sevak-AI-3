import 'dart:async';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sevakai_mobile/services/api_client.dart';
import 'package:sevakai_mobile/services/offline_queue.dart';
import 'package:sevakai_mobile/services/sync_service.dart';

class FakeQueue extends OfflineQueue {
  final List<String> ids;
  final acknowledged = <String>[];
  FakeQueue(int count) : ids = List.generate(count, (i) => '$i');
  @override
  Future<List<String>> pendingIds(String workerId) async => List.of(ids);
  @override
  Future<List<Map<String, dynamic>>> recordsByIds(String workerId, List<String> ids) async =>
      ids.map((id) => <String, dynamic>{'queue_id': id, 'record_json': '{"record_type":"visit"}'}).toList();
  @override
  Future<void> markSynced(String queueId) async { acknowledged.add(queueId); }
}

class FakeApi extends ApiClient {
  int calls = 0;
  final sizes = <int>[];
  Completer<void>? gate;
  bool failAll = false;
  @override
  Future<Map<String, dynamic>> syncBatch(String workerId, List<Map<String, dynamic>> records) async {
    calls++;
    sizes.add(records.length);
    if (gate != null) await gate!.future;
    return {'results': List.generate(records.length, (i) => {
      'index': i, 'status': failAll || i == 1 ? 'failed' : 'synced',
    })};
  }
}

void main() {
  test('overlapping flushes share one request and acknowledge only successes', () async {
    final api = FakeApi()..gate = Completer<void>();
    final queue = FakeQueue(3);
    final service = SyncService(api: api, queue: queue, workerId: 'test');
    final first = service.flushNow();
    final second = service.flushNow();
    expect(identical(first, second), isTrue);
    api.gate!.complete();
    expect(await first, {'synced': 2, 'failed': 1});
    expect(api.calls, 1);
    expect(queue.acknowledged, ['0', '2']);
    await service.dispose();
  });

  test('failing records are attempted once in finite bounded batches', () async {
    final api = FakeApi()..failAll = true;
    final service = SyncService(api: api, queue: FakeQueue(45), workerId: 'test');
    expect(await service.flushNow(), {'synced': 0, 'failed': 45});
    expect(api.sizes, [20, 20, 5]);
    await service.dispose();
  });

  test('start is idempotent; disposal cancels listener and blocks uploads', () async {
    final stream = StreamController<List<ConnectivityResult>>();
    final api = FakeApi();
    final service = SyncService(api: api, queue: FakeQueue(1), workerId: 'test',
        connectivityChanges: stream.stream);
    service.start();
    service.start();
    expect(stream.hasListener, isTrue);
    await service.dispose();
    expect(stream.hasListener, isFalse);
    await service.flushNow();
    expect(api.calls, 0);
    await stream.close();
  });

  test('disposal during upload prevents later batches and callbacks', () async {
    final api = FakeApi()..gate = Completer<void>();
    final service = SyncService(api: api, queue: FakeQueue(45), workerId: 'test');
    final pending = service.flushNow();
    await Future<void>.delayed(Duration.zero);
    expect(api.calls, 1);
    await service.dispose();
    api.gate!.complete();
    await pending;
    expect(api.calls, 1);
  });
}
