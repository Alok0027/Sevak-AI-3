import 'package:shared_preferences/shared_preferences.dart';

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

  static Future<void> save(Session session) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kToken, session.token);
    await prefs.setString(_kWorkerId, session.workerId);
    await prefs.setString(_kRole, session.role);
    await prefs.setString(_kWorkerName, session.workerName);
  }

  /// Returns null if there is no saved session (or it's incomplete).
  static Future<Session?> restore() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_kToken);
    final workerId = prefs.getString(_kWorkerId);
    final role = prefs.getString(_kRole);
    final workerName = prefs.getString(_kWorkerName);
    if (token == null || workerId == null || role == null || workerName == null) {
      return null;
    }
    return Session(token: token, workerId: workerId, role: role, workerName: workerName);
  }

  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kToken);
    await prefs.remove(_kWorkerId);
    await prefs.remove(_kRole);
    await prefs.remove(_kWorkerName);
  }
}
