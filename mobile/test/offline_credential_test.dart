import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
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
    // Session.save() still clears the legacy plaintext keys, so the
    // preferences plugin has to exist here even though nothing in these
    // tests reads it.
    SharedPreferences.setMockInitialValues({});
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

  // ── Signing out, and getting back in with no signal ──────────────────
  //
  // The first version deleted the session and the stored PIN on sign-out.
  // That meant an ASHA who signed out at lunch could not open her own
  // patient list again until she found a bar of signal -- the exact
  // situation the offline work exists for.

  Session sample() => Session(
        token: 'token-abc',
        workerId: 'w-1',
        role: 'asha',
        workerName: 'Sunita Sharma',
      );

  test('signing out shows the next person a sign-in screen', () async {
    await Session.save(sample());
    await Session.lock();
    expect(await Session.restore(), isNull,
        reason: 'a locked phone must not open straight into her ward');
  });

  test('...but her session is still there to be unlocked', () async {
    await Session.save(sample());
    await Session.lock();
    final locked = await Session.restoreLocked();
    expect(locked, isNotNull);
    expect(locked!.workerId, 'w-1');
    expect(locked.token, 'token-abc');
  });

  test('the right PIN offline gets her back in', () async {
    await Session.save(sample());
    await OfflineCredential.remember('9999999999', '1234');
    await Session.lock();

    expect(await Session.restore(), isNull);
    expect(await OfflineCredential.verify('9999999999', '1234'), isTrue);

    // What the login screen does once the PIN checks out.
    final locked = await Session.restoreLocked();
    await Session.save(locked!);
    expect(await Session.restore(), isNotNull,
        reason: 'unlocking should leave the app openable again');
  });

  test('a wrong PIN leaves it locked', () async {
    await Session.save(sample());
    await OfflineCredential.remember('9999999999', '1234');
    await Session.lock();

    expect(await OfflineCredential.verify('9999999999', '9999'), isFalse);
    expect(await Session.restore(), isNull);
  });

  test('clear still wipes everything, for a phone handed on for good', () async {
    await Session.save(sample());
    await Session.clear();
    expect(await Session.restore(), isNull);
    expect(await Session.restoreLocked(), isNull);
  });
}
