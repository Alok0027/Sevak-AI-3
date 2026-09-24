import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sevakai_mobile/services/session.dart';

/// Signing in with no signal.
///
/// The server owns the account and checks the PIN, which is right. But an
/// ASHA walks a ward for a day without a bar of signal, and signing out at
/// lunch used to lock her out of her own patient list until she found one.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });

  test('the PIN she used online opens the app offline', () async {
    await OfflineCredential.remember('9999999999', '1234');
    expect(await OfflineCredential.verify('9999999999', '1234'), isTrue);
  });

  test('a wrong PIN does not', () async {
    await OfflineCredential.remember('9999999999', '1234');
    expect(await OfflineCredential.verify('9999999999', '1235'), isFalse);
    expect(await OfflineCredential.verify('9999999999', ''), isFalse);
  });

  test('another worker on the same handset does not', () async {
    await OfflineCredential.remember('9999999999', '1234');
    expect(await OfflineCredential.verify('9999999901', '1234'), isFalse);
  });

  test('a phone that has never signed in online lets nobody in', () async {
    expect(await OfflineCredential.verify('9999999999', '1234'), isFalse);
  });

  test('signing out forgets it', () async {
    await OfflineCredential.remember('9999999999', '1234');
    await OfflineCredential.forget();
    expect(await OfflineCredential.verify('9999999999', '1234'), isFalse);
  });

  test('the PIN itself is never written to the device', () async {
    await OfflineCredential.remember('9999999999', '4321');
    final stored = await const FlutterSecureStorage()
        .read(key: 'sevakai_offline_credential_v1');
    expect(stored, isNotNull);
    expect(stored!.contains('4321'), isFalse,
        reason: 'a stored PIN is a stolen PIN once the handset is');
  });

  test('two phones storing the same PIN produce different hashes', () async {
    await OfflineCredential.remember('9999999999', '1234');
    final first = await const FlutterSecureStorage()
        .read(key: 'sevakai_offline_credential_v1');

    FlutterSecureStorage.setMockInitialValues({});
    await OfflineCredential.remember('9999999999', '1234');
    final second = await const FlutterSecureStorage()
        .read(key: 'sevakai_offline_credential_v1');

    expect(first, isNot(equals(second)),
        reason: 'a per-device salt is what stops one leaked hash opening '
            'every handset that shares a demo PIN');
  });
}
