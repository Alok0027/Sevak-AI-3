import 'package:flutter/material.dart';

import 'services/api_client.dart';
import 'services/session.dart';
import 'screens/login_screen.dart';
import 'screens/root_shell.dart';

void main() {
  runApp(const SevakAIApp());
}

class SevakAIApp extends StatelessWidget {
  const SevakAIApp({super.key});

  @override
  Widget build(BuildContext context) {
    final api = ApiClient(); // point baseUrl (api_client.dart) at your dev machine's LAN IP
    return MaterialApp(
      title: 'SevakAI',
      theme: ThemeData(colorSchemeSeed: const Color(0xFF1F6F4A), useMaterial3: true),
      home: _Bootstrap(api: api),
      debugShowCheckedModeBanner: false,
    );
  }
}

/// Restores a saved login (if any) before showing anything else, so an
/// ASHA worker doesn't have to sign in every time she opens the app --
/// important when she's doing a dozen home visits in a day.
class _Bootstrap extends StatefulWidget {
  final ApiClient api;
  const _Bootstrap({required this.api});

  @override
  State<_Bootstrap> createState() => _BootstrapState();
}

class _BootstrapState extends State<_Bootstrap> {
  late final Future<Session?> _sessionFuture;

  @override
  void initState() {
    super.initState();
    _sessionFuture = Session.restore();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Session?>(
      future: _sessionFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
        final session = snapshot.data;
        if (session == null) {
          return LoginScreen(api: widget.api);
        }
        widget.api.setToken(session.token);
        return RootShell(api: widget.api, session: session);
      },
    );
  }
}
