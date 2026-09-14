import 'package:flutter/material.dart';

import '../l10n/app_strings.dart';
import '../services/api_client.dart';
import '../theme/tokens.dart';
import '../widgets/status_group.dart';

/// Ask for an account.
///
/// SRS table 4 gives worker onboarding to the Admin panel, which is right
/// -- an ASHA is appointed to a post, she does not appoint herself -- but
/// it left no way for a new worker to start at all except an admin typing
/// her details off a phone call. This is the other half: she fills it in,
/// an admin checks it, and only then can she sign in.
///
/// She is not signed up when she taps Send. The server creates the account
/// as pending and returns no token, so this screen ends on a message
/// telling her what happens next, never on a logged-in app.
class RegisterScreen extends StatefulWidget {
  final ApiClient api;
  const RegisterScreen({super.key, required this.api});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _subCentre = TextEditingController();
  final _pin = TextEditingController();
  final _pinAgain = TextEditingController();

  String _role = 'asha';
  bool _sending = false;
  bool _sent = false;
  String? _error;

  static const _roles = <(String, String)>[
    ('asha', 'roleAsha'),
    ('anm', 'roleAnm'),
    ('bmo', 'roleBmo'),
    // Admin is absent on purpose: it is the role that creates every other
    // account and reads the audit log. The server rejects it too -- this
    // list is convenience, not the control.
  ];

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _subCentre.dispose();
    _pin.dispose();
    _pinAgain.dispose();
    super.dispose();
  }

  /// Checked here as well as on the server, because a round trip on a
  /// one-bar connection is a long time to wait to be told the PIN was
  /// three digits.
  String? _localProblem() {
    if (_name.text.trim().length < 2) return tr(context, 'nameTooShort');
    final digits = _phone.text.replaceAll(RegExp(r'\D'), '');
    if (digits.length != 10) return tr(context, 'phoneMustBe10Digits');
    final pin = _pin.text.trim();
    if (pin.length != 4 || int.tryParse(pin) == null) return tr(context, 'pinMustBe4Digits');
    if (pin != _pinAgain.text.trim()) return tr(context, 'pinsDoNotMatch');
    return null;
  }

  Future<void> _submit() async {
    final problem = _localProblem();
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    final taken = tr(context, 'phoneAlreadyRegistered');
    final language = Localizations.localeOf(context).languageCode;
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      await widget.api.register(
        name: _name.text.trim(),
        phone: _phone.text.replaceAll(RegExp(r'\D'), ''),
        pin: _pin.text.trim(),
        role: _role,
        subCentreId: _subCentre.text.trim().isEmpty ? null : _subCentre.text.trim(),
        languagePref: language,
      );
      if (!mounted) return;
      setState(() => _sent = true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.status == 409 ? taken : e.message);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr(context, 'register'))),
      body: _sent ? _confirmation(context) : _form(context),
    );
  }

  /// What happens next, in her words. Not a tick and a dismiss: she needs
  /// to know somebody may ring this number, and that she cannot sign in
  /// yet -- otherwise she tries, fails, and concludes it did not work.
  Widget _confirmation(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(T.s4),
      children: [
        const SizedBox(height: T.s8),
        const Center(child: Icon(Icons.mark_email_read_outlined, size: 56, color: T.forest)),
        const SizedBox(height: T.s4),
        Text(tr(context, 'requestSentTitle'), style: T.title, textAlign: TextAlign.center),
        const SizedBox(height: T.s2),
        Text(
          tr(context, 'requestSentBody'),
          style: T.body.copyWith(color: T.slate),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: T.s6),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(tr(context, 'backToSignIn')),
        ),
      ],
    );
  }

  Widget _form(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, T.s8),
      children: [
        Text(tr(context, 'registerTitle'), style: T.title),
        const SizedBox(height: T.s2),
        Text(tr(context, 'registerIntro'), style: T.body.copyWith(color: T.slate)),
        const SizedBox(height: T.s6),

        TextField(
          controller: _name,
          style: T.body,
          textCapitalization: TextCapitalization.words,
          decoration: InputDecoration(labelText: tr(context, 'fullName')),
        ),
        const SizedBox(height: T.s3),
        TextField(
          controller: _phone,
          style: T.body,
          keyboardType: TextInputType.phone,
          decoration: InputDecoration(labelText: tr(context, 'phone')),
        ),
        const SizedBox(height: T.s3),
        DropdownButtonFormField<String>(
          initialValue: _role,
          borderRadius: BorderRadius.circular(T.radius),
          decoration: InputDecoration(labelText: tr(context, 'yourRole')),
          items: [
            for (final (value, labelKey) in _roles)
              DropdownMenuItem(value: value, child: Text(tr(context, labelKey), style: T.body)),
          ],
          onChanged: (v) => setState(() => _role = v ?? 'asha'),
        ),
        const SizedBox(height: T.s3),
        TextField(
          controller: _subCentre,
          style: T.body,
          textCapitalization: TextCapitalization.characters,
          decoration: InputDecoration(
            labelText: tr(context, 'subCentre'),
            helperText: tr(context, 'subCentreHint'),
            helperMaxLines: 2,
          ),
        ),
        const SizedBox(height: T.s4),

        TextField(
          controller: _pin,
          style: T.body,
          keyboardType: TextInputType.number,
          obscureText: true,
          maxLength: 4,
          decoration: InputDecoration(labelText: tr(context, 'choosePin'), counterText: ''),
        ),
        const SizedBox(height: T.s3),
        TextField(
          controller: _pinAgain,
          style: T.body,
          keyboardType: TextInputType.number,
          obscureText: true,
          maxLength: 4,
          decoration: InputDecoration(labelText: tr(context, 'confirmPin'), counterText: ''),
          onSubmitted: (_) => _sending ? null : _submit(),
        ),

        if (_error != null) ...[
          const SizedBox(height: T.s3),
          Invitation(icon: Icons.error_outline_rounded, message: _error!),
        ],
        const SizedBox(height: T.s4),
        FilledButton(
          onPressed: _sending ? null : _submit,
          child: _sending
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                )
              : Text(tr(context, 'sendRequest')),
        ),
        const SizedBox(height: T.s2),
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(tr(context, 'backToSignIn')),
        ),
      ],
    );
  }
}
