import 'dart:convert';

import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';

import '../models/patient.dart';
import 'queue_cipher.dart';

/// The last patient list the server gave her, kept on the phone.
///
/// Without this the app saved work offline but could not be *used*
/// offline. The patient list was fetched on every open, so in a village
/// with no signal it showed "Failed to load" -- and since recording a
/// visit starts by tapping a patient in that list, the main flow stopped
/// at the first screen. Her forty existing patients were unreachable; the
/// only thing she could still do was register someone new.
///
/// Stored as the server's own JSON rather than as parsed fields, so a
/// cached list from an older app build still opens after an update: an
/// unknown key is ignored by [Patient.fromJson] exactly as it is when it
/// arrives over the wire.
///
/// Encrypted with the same key as the sync queue ([QueueCipher]). This is
/// a list of pregnant women's names, ages and villages sitting on a phone
/// that gets left in autos.
class PatientCache {
  static Database? _db;
  static Future<Database>? _opening;

  static Future<Database> get _database async {
    if (_db != null) return _db!;
    return _opening ??= _open().whenComplete(() => _opening = null);
  }

  static Future<Database> _open() async {
    // Its own file rather than a second table inside sevakai_offline.db.
    // That database holds unsent work: it has a migration that walks every
    // row, and `VACUUM` after it. A cache -- throwaway data that can always
    // be fetched again -- has no business sharing either.
    final path = join(await getDatabasesPath(), 'sevakai_cache.db');
    final opened = await openDatabase(
      path,
      version: 1,
      onCreate: (db, version) => db.execute('''
        CREATE TABLE patient_list (
          worker_id TEXT PRIMARY KEY,
          payload TEXT NOT NULL,
          saved_at TEXT NOT NULL
        )
      '''),
    );
    await opened.execute('PRAGMA secure_delete = ON');
    _db = opened;
    return opened;
  }

  /// Keep the newest good answer for this worker. One row per worker, so
  /// a shared handset does not show one ASHA another's ward.
  static Future<void> save(String workerId, String responseBody) async {
    final db = await _database;
    await db.insert(
      'patient_list',
      {
        'worker_id': workerId,
        'payload': await QueueCipher.encrypt(responseBody),
        'saved_at': DateTime.now().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// The saved list, or null if she has never loaded one on this phone.
  static Future<CachedPatients?> load(String workerId) async {
    final db = await _database;
    final rows = await db.query('patient_list',
        where: 'worker_id = ?', whereArgs: [workerId], limit: 1);
    if (rows.isEmpty) return null;
    try {
      final body = await QueueCipher.decrypt(rows.single['payload'] as String);
      final data = jsonDecode(body) as Map<String, dynamic>;
      final patients = (data['patients'] as List)
          .map((p) => Patient.fromJson(p as Map<String, dynamic>))
          .toList();
      return CachedPatients(
        patients: patients,
        savedAt: DateTime.parse(rows.single['saved_at'] as String),
      );
    } catch (_) {
      // A cache that cannot be read is not an error worth showing her --
      // it is the same situation as never having loaded one. The caller
      // falls back to the network error it already has.
      return null;
    }
  }

  /// Sign-out. The queue's key is deliberately kept (unsent visits must
  /// survive a logout) but her ward does not need to stay on the phone.
  static Future<void> clear() async {
    final db = await _database;
    await db.delete('patient_list');
  }
}

class CachedPatients {
  final List<Patient> patients;
  final DateTime savedAt;

  CachedPatients({required this.patients, required this.savedAt});
}
