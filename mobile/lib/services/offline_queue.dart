import 'dart:convert';

import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';

/// On-device mirror of the backend's `sync_queue` table (SRS section 6) --
/// this is what makes FR-07.1 ("app shall function fully offline") and
/// FR-01.3 (audio recorded offline syncs within 30s of connectivity) work.
class OfflineQueue {
  static Database? _db;

  Future<Database> get _database async {
    if (_db != null) return _db!;
    final path = join(await getDatabasesPath(), 'sevakai_offline.db');
    _db = await openDatabase(
      path,
      version: 1,
      onCreate: (db, version) => db.execute('''
        CREATE TABLE sync_queue (
          queue_id TEXT PRIMARY KEY,
          worker_id TEXT NOT NULL,
          record_type TEXT NOT NULL,
          record_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          synced_at TEXT,
          retry_count INTEGER NOT NULL DEFAULT 0
        )
      '''),
    );
    return _db!;
  }

  Future<void> enqueueVisit({
    required String workerId,
    required String patientId,
    required String audioBase64,
    required String languageCode,
  }) async {
    final db = await _database;
    final id = DateTime.now().microsecondsSinceEpoch.toString();
    await db.insert('sync_queue', {
      'queue_id': id,
      'worker_id': workerId,
      'record_type': 'visit',
      'record_json': jsonEncode({
        'record_type': 'visit',
        'patient_id': patientId,
        'audio_base64': audioBase64,
        'language_code': languageCode,
      }),
      'created_at': DateTime.now().toIso8601String(),
      'retry_count': 0,
    });
  }

  Future<List<Map<String, dynamic>>> unsyncedRecords(String workerId) async {
    final db = await _database;
    return db.query('sync_queue', where: 'worker_id = ? AND synced_at IS NULL', whereArgs: [workerId]);
  }

  Future<int> pendingCount(String workerId) async {
    final rows = await unsyncedRecords(workerId);
    return rows.length;
  }

  Future<void> markSynced(String queueId) async {
    final db = await _database;
    await db.update(
      'sync_queue',
      {'synced_at': DateTime.now().toIso8601String()},
      where: 'queue_id = ?',
      whereArgs: [queueId],
    );
  }

  Future<void> incrementRetry(String queueId) async {
    final db = await _database;
    await db.rawUpdate('UPDATE sync_queue SET retry_count = retry_count + 1 WHERE queue_id = ?', [queueId]);
  }
}
