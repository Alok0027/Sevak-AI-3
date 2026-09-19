import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sevakai_mobile/services/queue_cipher.dart';
import 'package:sevakai_mobile/services/session.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('legacy login migrates to secure storage and logout removes session only', () async {
    FlutterSecureStorage.setMockInitialValues({'offline_queue_key_v1': 'keep-this-key'});
    SharedPreferences.setMockInitialValues({'access_token': 'test-token', 'worker_id': 'worker', 'role': 'asha', 'worker_name': 'Test'});
    final session = await Session.restore();
    expect(session!.token, 'test-token');
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.containsKey('access_token'), isFalse);
    expect(await const FlutterSecureStorage().read(key: 'sevakai_session_v1'), isNotNull);
    await Session.clear();
    expect(await Session.restore(), isNull);
    expect(await const FlutterSecureStorage().read(key: 'offline_queue_key_v1'), 'keep-this-key');
  });
  test('queue encryption roundtrips, randomizes ciphertext and rejects tampering', () async {
    FlutterSecureStorage.setMockInitialValues({});
    final first = await QueueCipher.encrypt('reviewed patient observations');
    final second = await QueueCipher.encrypt('reviewed patient observations');
    expect(first, isNot(second));
    expect(first.contains('patient'), isFalse);
    expect(await QueueCipher.decrypt(first), 'reviewed patient observations');
    final bytes = base64Decode(first.substring(5));
    bytes[15] ^= 1;
    await expectLater(QueueCipher.decrypt('enc1:${base64Encode(bytes)}'), throwsA(anything));
    await expectLater(QueueCipher.decrypt('plaintext'), throwsFormatException);
  });
}
