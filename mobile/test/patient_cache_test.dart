import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:sevakai_mobile/services/patient_cache.dart';

/// The app saved work offline but could not be used offline: the patient
/// list was fetched every time, so with no signal it showed "Failed to
/// load" -- and recording a visit starts by tapping a patient in that
/// list, so the whole flow stopped at the first screen.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory directory;

  // One directory for the whole file, not one per test.
  //
  // PatientCache holds its database open in a static field, which is right
  // for an app -- one handle for its lifetime -- and means a fresh temp
  // directory per test leaves that handle pointing at the previous one.
  // The cache then writes to the old file while the assertions read a new
  // empty one, and two tests fail for a reason that has nothing to do with
  // the code under test.
  setUpAll(() async {
    FlutterSecureStorage.setMockInitialValues({});
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
    directory = await Directory.systemTemp.createTemp('sevakai-cache-test-');
    await databaseFactory.setDatabasesPath(directory.path);
  });

  setUp(() async {
    await PatientCache.clear();
  });

  String body(List<Map<String, dynamic>> patients) =>
      jsonEncode({'patients': patients, 'attention_count': 0});

  /// A second handle on the same file, for looking at what was actually
  /// written.
  ///
  /// `singleInstance: false` is the whole point. sqflite hands back the
  /// *same* Database object for a path by default, so a plain
  /// openDatabase here returns PatientCache's own handle -- and closing it
  /// after the check closed the cache's database for every test that
  /// followed. Five tests failed on "database_closed" for a reason that
  /// had nothing to do with them.
  Future<Database> inspect() => openDatabase(
        '${directory.path}/sevakai_cache.db',
        options: OpenDatabaseOptions(singleInstance: false),
      );

  test('a saved list comes back after the network is gone', () async {
    await PatientCache.save(
      'worker-1',
      body([
        {'id': 'p1', 'name': 'Meera Patil', 'age': 28, 'village': 'Wagholi',
         'pregnancy_stage': '7 months', 'risk_status': 'HIGH', 'total_visits': 3,
         'needs_attention': true},
        {'id': 'p2', 'name': 'Kamla Devi', 'age': 34, 'village': 'Shirur',
         'risk_status': 'LOW', 'total_visits': 1},
      ]),
    );

    final cached = await PatientCache.load('worker-1');
    expect(cached, isNotNull);
    expect(cached!.patients.length, 2);
    expect(cached.patients.first.name, 'Meera Patil');
    expect(cached.patients.first.riskStatus, 'HIGH');
    expect(cached.patients.first.needsAttention, isTrue);
    // She needs to be told how old it is, so the header can say so.
    expect(cached.savedAt.isAfter(DateTime.now().subtract(const Duration(minutes: 1))), isTrue);
  });

  test('the names are not readable in the database file', () async {
    await PatientCache.save('worker-1',
        body([{'id': 'p1', 'name': 'Meera Patil', 'total_visits': 0}]));

    final db = await inspect();
    final raw = (await db.query('patient_list')).single['payload'] as String;
    await db.close();

    expect(raw.contains('Meera Patil'), isFalse,
        reason: 'a list of pregnant women lives on a phone that gets left in autos');
    expect(raw.startsWith('enc1:'), isTrue);
  });

  test('a later list replaces the earlier one rather than piling up', () async {
    await PatientCache.save('worker-1',
        body([{'id': 'p1', 'name': 'Old Name', 'total_visits': 0}]));
    await PatientCache.save('worker-1',
        body([{'id': 'p1', 'name': 'Corrected Name', 'total_visits': 0}]));

    final cached = await PatientCache.load('worker-1');
    expect(cached!.patients.single.name, 'Corrected Name');
  });

  test('one worker never sees another worker ward on a shared handset', () async {
    await PatientCache.save('worker-1',
        body([{'id': 'p1', 'name': 'Sunita patient', 'total_visits': 0}]));
    await PatientCache.save('worker-2',
        body([{'id': 'p2', 'name': 'Kavya patient', 'total_visits': 0}]));

    expect((await PatientCache.load('worker-1'))!.patients.single.name, 'Sunita patient');
    expect((await PatientCache.load('worker-2'))!.patients.single.name, 'Kavya patient');
  });

  test('never loaded on this phone returns nothing, not an error', () async {
    expect(await PatientCache.load('worker-never-seen'), isNull);
  });

  test('an unreadable row is treated as no cache rather than crashing', () async {
    await PatientCache.save('worker-1',
        body([{'id': 'p1', 'name': 'Meera Patil', 'total_visits': 0}]));
    final db = await inspect();
    await db.update('patient_list', {'payload': 'enc1:not-actually-ciphertext'});
    await db.close();

    expect(await PatientCache.load('worker-1'), isNull);
  });

  test('sign-out clears her ward off the phone', () async {
    await PatientCache.save('worker-1',
        body([{'id': 'p1', 'name': 'Meera Patil', 'total_visits': 0}]));
    await PatientCache.clear();
    expect(await PatientCache.load('worker-1'), isNull);
  });
}
