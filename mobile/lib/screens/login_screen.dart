import 'dart:async';
import 'package:flutter/material.dart';

import '../l10n/app_strings.dart';
import '../widgets/language_picker.dart';
import '../services/api_client.dart';
import '../services/session.dart';
import 'register_screen.dart';
import 'root_shell.dart';

class LoginScreen extends StatefulWidget {
  final ApiClient api;
  const LoginScreen({super.key, required this.api});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phoneController = TextEditingController(text: '9999999999');
  final _pinController = TextEditingController(text: '1234');
  bool _loading = false;
  String? _error;
  bool _waking = false;
  Timer? _wakeNotice;

  /// Unlock the session this phone already holds, if the PIN matches.
  ///
  /// Returns the session on success and null when there is nothing saved,
  /// the worker is different, or the PIN is wrong -- in which case the
  /// caller shows the network error, which is the honest thing to show:
  /// the server really was unreachable.
  Future<Session?> _offlineSignIn() async {
    final phone = _phoneController.text.trim();
    final pin = _pinController.text.trim();
    if (!await OfflineCredential.verify(phone, pin)) return null;
    // restoreLocked, not restore: she is signing in *because* the session
    // is locked, and restore() refuses a locked one by design.
    final session = await Session.restoreLocked();
    if (session == null) return null;
    await Session.save(session);  // unlocked again
    widget.api.setToken(session.token);
    if (!mounted) return null;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(tr(context, 'signedInOffline'))),
    );
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => RootShell(api: widget.api, session: session)),
    );
    return session;
  }

  @override
  void dispose() {
    // Without this the timer fires into a disposed widget when she backs
    // out mid-login, and setState throws after unmount.
    _wakeNotice?.cancel();
    super.dispose();
  }

  Future<void> _login() async {
    setState(() {
      _loading = true;
      _error = null;
      _waking = false;
    });
    // The backend sleeps on its host's free tier and takes the better part
    // of a minute to wake. Signing in over that gap looks identical to a
    // frozen app, so after a few seconds say what is actually happening
    // rather than leaving her watching a spinner.
    _wakeNotice = Timer(const Duration(seconds: 4), () {
      if (mounted && _loading) setState(() => _waking = true);
    });
    try {
      final phone = _phoneController.text.trim();
      final pin = _pinController.text.trim();
      final result = await widget.api.login(phone, pin);
      final session = Session(
        token: result['access_token'] as String,
        workerId: result['worker_id'] as String,
        role: result['role'] as String,
        workerName: result['worker_name'] as String,
      );
      await Session.save(session);
      // Remember enough to check this same PIN here tomorrow, when she is
      // three villages out with no bar of signal.
      await OfflineCredential.remember(phone, pin);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => RootShell(api: widget.api, session: session)),
      );
    } catch (e) {
      // Could not reach the server. If this phone has signed in online
      // before, as this worker, with this PIN, let her in on what it
      // already holds -- refusing her here would strand her from her own
      // patient list for the rest of a day in the field.
      //
      // Only a network failure opens this door. A 401 is the server
      // saying the PIN is wrong and a 403 is her account not being
      // approved; both are answers, and neither may be second-guessed
      // offline.
      final networkFailure = e is! ApiException;
      if (networkFailure) {
        final session = await _offlineSignIn();
        if (session != null) return;
      }
      if (mounted) setState(() => _error = readableError(e));
    } finally {
      _wakeNotice?.cancel();
      if (mounted) setState(() { _loading = false; _waking = false; });
    }
  }



  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('SevakAI'),
        // Before sign-in too: a worker should be able to pick her language
        // before she has to read anything else.
        actions: const [LanguagePicker()],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // The emblem, not a Material glyph. This is the first
              // screen an ASHA sees and the one a reviewer screenshots,
              // and a stock health icon says nothing about whose service
              // this is. Bundled as an asset rather than fetched, because
              // she may well be opening the app with no signal.
              Image.asset(
                'assets/brand/sevakai_emblem.png',
                height: 112,
                // If the asset is ever missing from a build, a broken
                // image box on the sign-in screen looks like a broken
                // app. Fall back to the old glyph instead.
                errorBuilder: (_, __, ___) =>
                    const Icon(Icons.health_and_safety, size: 56, color: Color(0xFF14624A)),
              ),
              const SizedBox(height: 12),
              Text(
                tr(context, 'signIn'),
                style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 4),
              Text(
                tr(context, 'loginSubtitle'),
                style: TextStyle(color: Colors.grey.shade600),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              TextField(
                controller: _phoneController,
                decoration: InputDecoration(
                  labelText: tr(context, 'phone'),
                  border: const OutlineInputBorder(),
                  prefixIcon: const Icon(Icons.phone),
                ),
                keyboardType: TextInputType.phone,
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _pinController,
                decoration: InputDecoration(
                  labelText: tr(context, 'pin'),
                  border: const OutlineInputBorder(),
                  prefixIcon: const Icon(Icons.lock_outline),
                ),
                keyboardType: TextInputType.number,
                obscureText: true,
                onSubmitted: (_) => _loading ? null : _login(),
              ),
              const SizedBox(height: 20),
              if (_waking && _error == null)
                const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: Text(
                    'Waking the server, please wait…',
                    style: TextStyle(fontSize: 13, color: Colors.black54),
                    textAlign: TextAlign.center,
                  ),
                ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(_error!, style: const TextStyle(color: Colors.red), textAlign: TextAlign.center),
                ),
              FilledButton(
                onPressed: _loading ? null : _login,
                child: _loading
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                    : Text(tr(context, 'login')),
              ),
              const SizedBox(height: 8),
              TextButton(
                onPressed: _loading
                    ? null
                    : () => Navigator.of(context).push(
                          MaterialPageRoute(builder: (_) => RegisterScreen(api: widget.api)),
                        ),
                child: Text(tr(context, 'noAccountYet')),
              ),
              const SizedBox(height: 8),
              Text(
                tr(context, 'demoAsha'),
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.grey),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
