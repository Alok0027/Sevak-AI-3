import 'dart:convert';
import 'dart:math';

import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';
import 'queue_cipher.dart';

/// On-device mirror of the backend's `sync_queue` table (SRS section 6) --
/// this is what makes FR-07.1 ("app shall function fully offline") and
/// FR-01.3 (audio recorded offline syncs within 30s of connectivity) work.
class OfflineQueue {
  static Database? _db;
  static Future<Database>? _opening;

  Future<Database> get _database async {
    if (_db != null) return _db!;
    return _opening ??= _open().whenComplete(() => _opening = null);
  }

  Future<Database> _open() async {
    final path = join(await getDatabasesPath(), 'sevakai_offline.db');
    final opened = await openDatabase(
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
    try {
      // rawQuery, not execute, and never fatal.
      //
      // `PRAGMA secure_delete = ON` *returns* the value it set, which makes
      // it a query. Android's SQLiteDatabase refuses a returning statement
      // through execSQL and throws "Queries can be performed using
      // SQLiteDatabase query or rawQuery methods only". sqflite_ffi -- what
      // the tests and the emulator use -- allows it, so this passed every
      // test and failed on the first real handset.
      //
      // Wrapped because secure_delete is hardening, not function: it makes
      // deleted rows unrecoverable from the file. If a device or a SQLite
      // build will not do it, an ASHA must still be able to record a visit.
      try {
        await opened.rawQuery('PRAGMA secure_delete = ON');
      } catch (_) {
        // Continue without it rather than refusing to open the database.
      }
      // Migrate one record at a time; never load the complete audio backlog.
      final ids = await opened.query('sync_queue', columns: ['queue_id']);
      var migrated = false;
      for (final row in ids) {
        final rows = await opened.query('sync_queue', where: 'queue_id = ?', whereArgs: [row['queue_id']]);
        final value = rows.single['record_json'] as String;
        if (!value.startsWith('enc1:')) {
          migrated = true;
          await opened.update('sync_queue', {'record_json': await QueueCipher.encrypt(value)},
              where: 'queue_id = ?', whereArgs: [row['queue_id']]);
        }
      }
      if (migrated) {
        await opened.rawQuery('PRAGMA wal_checkpoint(TRUNCATE)');
        await opened.execute('VACUUM');
      }
      _db = opened;
      return opened;
    } catch (_) {
      await opened.close();
      rethrow;
    }
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
    String? rchNumber,
    // Her spoken introduction of the woman, when she recorded one with no
    // signal. The phone cannot transcribe -- speech recognition lives on
    // the server -- so the audio travels with the record and is parsed on
    // sync, filling only the fields she did not type herself.
    String? audioBase64,
    String? languageCode,
  }) async {
    final db = await _database;
    await db.insert('sync_queue', {
      'queue_id': newLocalId(),
      'worker_id': workerId,
      'record_type': 'patient',
      'record_json': await QueueCipher.encrypt(jsonEncode({
        'record_type': 'patient',
        'patient_id': patientId,
        'name': name,
        'age': age,
        'gender': gender,
        'village': village,
        'phone': phone,
        'pregnancy_stage': pregnancyStage,
        'rch_number': rchNumber,
        if (audioBase64 != null) 'audio_base64': audioBase64,
        if (audioBase64 != null) 'language_code': languageCode ?? 'hi',
      })),
      'created_at': DateTime.now().toIso8601String(),
      'retry_count': 0,
    });
  }

  Future<void> enqueueVisit({
    required String workerId,
    required String patientId,
    String? audioBase64,
    required String languageCode,
    String? confirmedTranscript,
    Map<String, dynamic>? confirmedExtracted,
    String? clientRequestId,
  }) async {
    final db = await _database;
    final id = clientRequestId ?? newLocalId();
    await db.insert('sync_queue', {
      'queue_id': id,
      'worker_id': workerId,
      'record_type': 'visit',
      'record_json': await QueueCipher.encrypt(jsonEncode({
        'record_type': 'visit',
        'patient_id': patientId,
        'audio_base64': audioBase64,
        'language_code': languageCode,
        'client_request_id': id,
        if (confirmedTranscript != null) 'confirmed_transcript': confirmedTranscript,
        if (confirmedExtracted != null) 'confirmed_extracted': confirmedExtracted,
      })),
      'created_at': DateTime.now().toIso8601String(),
      'retry_count': 0,
    }, conflictAlgorithm: ConflictAlgorithm.ignore);
  }

  Future<List<Map<String, dynamic>>> unsyncedRecords(String workerId) async {
    final db = await _database;
    final rows = await db.query('sync_queue', where: 'worker_id = ? AND synced_at IS NULL', whereArgs: [workerId]);
    return _decryptRows(rows);
  }

  Future<int> pendingCount(String workerId) async {
    final db = await _database;
    return Sqflite.firstIntValue(await db.rawQuery(
      'SELECT COUNT(*) FROM sync_queue WHERE worker_id = ? AND synced_at IS NULL',
      [workerId],
    )) ?? 0;
  }

  Future<List<String>> pendingIds(String workerId) async {
    final db = await _database;
    final rows = await db.query('sync_queue', columns: ['queue_id'],
      where: 'worker_id = ? AND synced_at IS NULL', whereArgs: [workerId],
      orderBy: "CASE WHEN record_type = 'patient' THEN 0 ELSE 1 END, created_at, queue_id");
    return rows.map((row) => row['queue_id'] as String).toList();
  }

  Future<List<Map<String, dynamic>>> recordsByIds(String workerId, List<String> ids) async {
    if (ids.isEmpty) return [];
    final db = await _database;
    final rows = await db.query('sync_queue',
      where: 'worker_id = ? AND synced_at IS NULL AND queue_id IN (${List.filled(ids.length, '?').join(',')})',
      whereArgs: [workerId, ...ids]);
    final byId = {for (final row in rows) row['queue_id']: row};
    return _decryptRows([for (final id in ids) if (byId.containsKey(id)) byId[id]!]);
  }

  Future<List<Map<String, dynamic>>> _decryptRows(List<Map<String, dynamic>> rows) async {
    return [for (final row in rows) {...row,
      'record_json': await QueueCipher.decrypt(row['record_json'] as String)}];
  }

  Future<void> markSynced(String queueId) async {
    final db = await _database;
    await db.delete(
      'sync_queue',
      where: 'queue_id = ?',
      whereArgs: [queueId],
    );
  }

  Future<void> incrementRetry(String queueId) async {
    final db = await _database;
    await db.rawUpdate('UPDATE sync_queue SET retry_count = retry_count + 1 WHERE queue_id = ?', [queueId]);
  }
}
