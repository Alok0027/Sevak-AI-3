import 'package:shared_preferences/shared_preferences.dart';
import 'dart:convert';
import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// A logged-in ASHA worker's identity, persisted to disk so the app can
/// skip the login screen on relaunch -- a field worker doing a dozen home
/// visits a day shouldn't have to sign in every time she opens the app.
class Session {
  final String token;
  final String workerId;
  final String role;
  final String workerName;

  Session({
    required this.token,
    required this.workerId,
    required this.role,
    required this.workerName,
  });

  static const _kToken = 'access_token';
  static const _kWorkerId = 'worker_id';
  static const _kRole = 'role';
  static const _kWorkerName = 'worker_name';
  static const _secure = FlutterSecureStorage();
  static const _sessionKey = 'sevakai_session_v1';

  static Future<void> save(Session session, {bool locked = false}) async {
    await _secure.write(key: _sessionKey, value: jsonEncode({
      'token': session.token, 'workerId': session.workerId,
      'role': session.role, 'workerName': session.workerName,
      'locked': locked,
    }));
    final prefs = await SharedPreferences.getInstance();
    for (final key in [_kToken, _kWorkerId, _kRole, _kWorkerName]) {
      await prefs.remove(key);
    }
  }

  /// The session to open the app with, or null to show the sign-in screen.
  ///
  /// A locked session is not returned: signing out has to mean the next
  /// person picking up the phone sees a PIN prompt, not her patient list.
  static Future<Session?> restore() async {
    final secured = await _secure.read(key: _sessionKey);
    if (secured != null) {
      final data = jsonDecode(secured) as Map<String, dynamic>;
      if (data['locked'] == true) return null;
      return Session(token: data['token'], workerId: data['workerId'],
          role: data['role'], workerName: data['workerName']);
    }
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_kToken);
    final workerId = prefs.getString(_kWorkerId);
    final role = prefs.getString(_kRole);
    final workerName = prefs.getString(_kWorkerName);
    if (token == null || workerId == null || role == null || workerName == null) {
      return null;
    }
    final session = Session(token: token, workerId: workerId, role: role, workerName: workerName);
    await save(session); // Remove plaintext only after secure storage succeeds.
    return session;
  }

  /// Sign out without throwing away what lets her back in.
  ///
  /// Deleting the session outright is what broke offline sign-in: after
  /// signing out at lunch there was nothing left on the phone to check a
  /// PIN against, so an ASHA in a village with no signal could not open
  /// her own patient list again until she found a bar.
  ///
  /// Locking keeps the token and the stored PIN hash, and marks the
  /// session closed so `restore()` refuses it -- the next person to pick
  /// up the phone gets the sign-in screen. Her PIN is the gate, exactly as
  /// it is online. A phone being handed on for good wants `clear()`.
  static Future<void> lock() async {
    final secured = await _secure.read(key: _sessionKey);
    if (secured == null) return;
    final data = jsonDecode(secured) as Map<String, dynamic>;
    data['locked'] = true;
    await _secure.write(key: _sessionKey, value: jsonEncode(data));
  }

  /// The locked session, for the PIN check that is about to unlock it.
  static Future<Session?> restoreLocked() async {
    final secured = await _secure.read(key: _sessionKey);
    if (secured == null) return null;
    try {
      final data = jsonDecode(secured) as Map<String, dynamic>;
      return Session(token: data['token'], workerId: data['workerId'],
          role: data['role'], workerName: data['workerName']);
    } catch (_) {
      return null;
    }
  }

  static Future<void> clear() async {
    await _secure.delete(key: _sessionKey);
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kToken);
    await prefs.remove(_kWorkerId);
    await prefs.remove(_kRole);
    await prefs.remove(_kWorkerName);
  }
}

/// Signing in with no signal.
///
/// Her PIN is checked by the server, which is right: the server owns the
/// account, and a phone that could mint its own sessions would be a way
/// in for anyone holding it. But an ASHA walks a ward for a day without
/// signal, and a supervisor's phone she borrowed, a restart, or simply
/// signing out at lunch then left her unable to open her own patient list
/// until she found a bar of signal.
///
/// So after a successful *online* sign-in the phone keeps enough to check
/// the same PIN itself: a random salt, and PBKDF2 over the PIN with it.
/// The PIN is never stored, and the stored hash is useless on any other
/// device because the salt lives in platform secure storage beside it.
///
/// This grants no new access. It unlocks the session the server already
/// issued to this phone, for this worker -- nothing more. The token it
/// returns is the one she was given online, and the server still refuses
/// it if it has expired or her account has been suspended.
class OfflineCredential {
  static const _secure = FlutterSecureStorage();
  static const _key = 'sevakai_offline_credential_v1';

  /// Rounds are a tradeoff, not a ritual. High enough that a stolen phone
  /// does not yield a four-digit PIN to a quick script, low enough that an
  /// ASHA on a three-year-old handset is not left staring at a spinner.
  static const _iterations = 20000;

  static Future<void> remember(String phone, String pin) async {
    final salt = SecretKeyData.random(length: 16).bytes;
    final hash = await _derive(pin, salt);
    await _secure.write(
      key: _key,
      value: jsonEncode({
        'phone': phone,
        'salt': base64Encode(salt),
        'hash': base64Encode(hash),
      }),
    );
  }

  /// True when this phone number and PIN match what was stored at her last
  /// online sign-in. False for a different worker, a wrong PIN, or a phone
  /// that has never been signed into.
  static Future<bool> verify(String phone, String pin) async {
    final saved = await _secure.read(key: _key);
    if (saved == null) return false;
    try {
      final data = jsonDecode(saved) as Map<String, dynamic>;
      if (data['phone'] != phone) return false;
      final expected = base64Decode(data['hash'] as String);
      final actual = await _derive(pin, base64Decode(data['salt'] as String));
      return _constantTimeEquals(expected, actual);
    } catch (_) {
      return false;
    }
  }

  static Future<void> forget() => _secure.delete(key: _key);

  static Future<List<int>> _derive(String pin, List<int> salt) async {
    final pbkdf2 = Pbkdf2(
      macAlgorithm: Hmac.sha256(),
      iterations: _iterations,
      bits: 256,
    );
    final key = await pbkdf2.deriveKey(
      secretKey: SecretKey(utf8.encode(pin)),
      nonce: salt,
    );
    return key.extractBytes();
  }

  /// Compared byte by byte without an early exit. An `==` that returns as
  /// soon as two bytes differ leaks, in its timing, how much of a guess
  /// was right -- which is enough to walk a four-digit PIN one digit at a
  /// time.
  static bool _constantTimeEquals(List<int> a, List<int> b) {
    if (a.length != b.length) return false;
    var difference = 0;
    for (var i = 0; i < a.length; i++) {
      difference |= a[i] ^ b[i];
    }
    return difference == 0;
  }
}
