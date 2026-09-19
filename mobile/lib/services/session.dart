import 'package:shared_preferences/shared_preferences.dart';
import 'dart:convert';
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

  static Future<void> save(Session session) async {
    await _secure.write(key: _sessionKey, value: jsonEncode({
      'token': session.token, 'workerId': session.workerId,
      'role': session.role, 'workerName': session.workerName,
    }));
    final prefs = await SharedPreferences.getInstance();
    for (final key in [_kToken, _kWorkerId, _kRole, _kWorkerName]) {
      await prefs.remove(key);
    }
  }

  /// Returns null if there is no saved session (or it's incomplete).
  static Future<Session?> restore() async {
    final secured = await _secure.read(key: _sessionKey);
    if (secured != null) {
      final data = jsonDecode(secured) as Map<String, dynamic>;
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

  static Future<void> clear() async {
    await _secure.delete(key: _sessionKey);
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kToken);
    await prefs.remove(_kWorkerId);
    await prefs.remove(_kRole);
    await prefs.remove(_kWorkerName);
  }
}
