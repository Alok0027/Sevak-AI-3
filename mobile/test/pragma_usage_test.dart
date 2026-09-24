import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// A source check, because no runtime test can catch this one.
///
/// `PRAGMA foo = bar` returns the value it set, so it is a query. Android's
/// SQLiteDatabase refuses a returning statement through execSQL and throws
/// "Queries can be performed using SQLiteDatabase query or rawQuery methods
/// only". sqflite_ffi -- which the emulator and every test in this suite
/// use -- allows it.
///
/// So the bug passed all 17 tests and appeared on the first real handset,
/// as a red banner where an ASHA had just recorded a visit. The only place
/// it can be caught before shipping is here, in the source.
void main() {
  test('setting PRAGMAs goes through rawQuery, never execute', () {
    final offenders = <String>[];

    for (final entity in Directory('lib').listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final lines = entity.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        final line = lines[i];
        if (!line.contains('PRAGMA')) continue;
        // A PRAGMA that assigns returns its new value; one that only reads
        // is a query either way. Both belong in rawQuery.
        if (line.contains('.execute(')) {
          offenders.add('${entity.path}:${i + 1}  ${line.trim()}');
        }
      }
    }

    expect(
      offenders,
      isEmpty,
      reason: 'these PRAGMAs will throw on a real Android device -- '
          'use rawQuery instead of execute:\n${offenders.join('\n')}',
    );
  });
}
