import 'dart:convert';
import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// AES-GCM payload encryption. The key stays in platform secure storage,
/// never alongside the SQLite file. Authentication failures are not ignored.
class QueueCipher {
  static const storage = FlutterSecureStorage();
  static final algorithm = AesGcm.with256bits();
  static Future<SecretKey>? _keyFuture;
  static Future<SecretKey> _key() => _keyFuture ??= _loadKey();
  static Future<SecretKey> _loadKey() async {
    final saved = await storage.read(key: 'offline_queue_key_v1');
    if (saved != null) return SecretKey(base64Decode(saved));
    final key = await algorithm.newSecretKey();
    await storage.write(key: 'offline_queue_key_v1', value: base64Encode(await key.extractBytes()));
    return key;
  }
  static Future<String> encrypt(String plaintext) async {
    final box = await algorithm.encrypt(utf8.encode(plaintext), secretKey: await _key());
    return 'enc1:${base64Encode(box.concatenation())}';
  }
  static Future<String> decrypt(String value) async {
    if (!value.startsWith('enc1:')) throw const FormatException('Unencrypted queue record');
    final box = SecretBox.fromConcatenation(base64Decode(value.substring(5)), nonceLength: 12, macLength: 16);
    return utf8.decode(await algorithm.decrypt(box, secretKey: await _key()));
  }
}
