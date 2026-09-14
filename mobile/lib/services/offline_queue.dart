import 'dart:convert';
import 'dart:math';

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

  /// A patient id the phone can mint with no server and no signal.
  ///
  /// The backend's patient_id is a plain string primary key, so an id
  /// generated here survives sync unchanged -- which is the whole point: a
  /// visit recorded minutes after an offline registration references this
  /// id, and both resolve when the queue flushes. A server-assigned id
  /// would arrive too late to be referenced.
  ///
  /// Formatted as a v4 UUID rather than a timestamp so it cannot collide
  /// with another ASHA's offline registration in the same second, and
  /// Random.secure() rather than Random() because two phones starting from
  /// the same seed is exactly the collision that matters.
  static String newLocalId() {
    final r = Random.secure();
    String hex(int n) => List.generate(n, (_) => r.nextInt(16).toRadixString(16)).join();
    // Version 4, variant 1 -- the two fixed nibbles that mark it as random.
    return '${hex(8)}-${hex(4)}-4${hex(3)}-'
        '${(8 + r.nextInt(4)).toRadixString(16)}${hex(3)}-${hex(12)}';
  }

  /// FR-07.1: a patient registered with no signal.
  ///
  /// Queued with the id already decided, so the visits she is about to
  /// receive can reference her before the server has ever heard of her.
  Future<void> enqueuePatient({
    required String workerId,
    required String patientId,
    required String name,
    int? age,
    String? gender,
    String? village,
    String? phone,
    String? pregnancyStage,
  }) async {
    final db = await _database;
    await db.insert('sync_queue', {
      'queue_id': DateTime.now().microsecondsSinceEpoch.toString(),
      'worker_id': workerId,
      'record_type': 'patient',
      'record_json': jsonEncode({
        'record_type': 'patient',
        'patient_id': patientId,
        'name': name,
        'age': age,
        'gender': gender,
        'village': village,
        'phone': phone,
        'pregnancy_stage': pregnancyStage,
      }),
      'created_at': DateTime.now().toIso8601String(),
      'retry_count': 0,
    });
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
