import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:sevakai_mobile/services/offline_queue.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('plaintext queue migrates; reviewed fields survive; only acknowledged row is deleted', () async {
    FlutterSecureStorage.setMockInitialValues({});
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
    final directory = await Directory.systemTemp.createTemp('sevakai-queue-test-');
    await databaseFactory.setDatabasesPath(directory.path);
    final db = await openDatabase('${directory.path}/sevakai_offline.db', version: 1,
      onCreate: (db, version) => db.execute('CREATE TABLE sync_queue (queue_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, record_type TEXT NOT NULL, record_json TEXT NOT NULL, created_at TEXT NOT NULL, synced_at TEXT, retry_count INTEGER NOT NULL DEFAULT 0)'));
    await db.insert('sync_queue', {'queue_id':'legacy', 'worker_id':'worker', 'record_type':'visit',
      'record_json':jsonEncode({'record_type':'visit', 'audio_base64':'test-only-audio', 'patient_id':'patient', 'language_code':'hi'}),
      'created_at':'2026-01-01T00:00:00Z'});
    await db.close();
    final queue = OfflineQueue();
    expect(await queue.pendingCount('worker'), 1);
    await queue.enqueueVisit(workerId:'worker', patientId:'patient', languageCode:'hi',
      confirmedTranscript:'Reviewed exact text', confirmedExtracted:{'bp_systolic':123}, clientRequestId:'reviewed');
    final rows = await queue.unsyncedRecords('worker');
    final reviewed = jsonDecode(rows.singleWhere((r) => r['queue_id'] == 'reviewed')['record_json'] as String);
    expect(reviewed['confirmed_transcript'], 'Reviewed exact text');
    expect(reviewed['confirmed_extracted']['bp_systolic'], 123);
    expect(reviewed['client_request_id'], 'reviewed');
    expect(await queue.pendingCount('other-worker'), 0);
    final inspect = await openDatabase('${directory.path}/sevakai_offline.db');
    for (final row in await inspect.query('sync_queue')) {
      expect((row['record_json'] as String).startsWith('enc1:'), isTrue);
    }
    await queue.markSynced('reviewed');
    expect(await queue.pendingCount('worker'), 1);
    expect((await inspect.query('sync_queue')).single['queue_id'], 'legacy');
    await inspect.close();
    await directory.delete(recursive: true); // Only this test's unique temporary directory.
  });
}
