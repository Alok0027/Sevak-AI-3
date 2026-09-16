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

  Future<void> _login() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.api.login(_phoneController.text.trim(), _pinController.text.trim());
      final session = Session(
        token: result['access_token'] as String,
        workerId: result['worker_id'] as String,
        role: result['role'] as String,
        workerName: result['worker_name'] as String,
      );
      await Session.save(session);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => RootShell(api: widget.api, session: session)),
      );
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
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
