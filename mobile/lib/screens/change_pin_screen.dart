import 'package:flutter/material.dart';

import '../l10n/app_strings.dart';
import '../services/api_client.dart';
import '../theme/tokens.dart';
import '../widgets/status_group.dart';

/// Change the PIN somebody else chose for you.
///
/// Every account here starts with a PIN set by an admin, or handed out at
/// a block meeting. Until this screen existed there was no way to change
/// it, which meant "her" PIN was permanently known to whoever set it, and
/// a PIN shared across a sub-centre could never be unshared.
///
/// Nothing about that ever failed, which is why it went unnoticed.
class ChangePinScreen extends StatefulWidget {
  final ApiClient api;
  const ChangePinScreen({super.key, required this.api});

  @override
  State<ChangePinScreen> createState() => _ChangePinScreenState();
}

class _ChangePinScreenState extends State<ChangePinScreen> {
  final _current = TextEditingController();
  final _next = TextEditingController();
  final _nextAgain = TextEditingController();
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    _nextAgain.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final next = _next.text.trim();
    if (next.length != 4 || int.tryParse(next) == null) {
      setState(() => _error = tr(context, 'pinMustBe4Digits'));
      return;
    }
    if (next != _nextAgain.text.trim()) {
      setState(() => _error = tr(context, 'pinsDoNotMatch'));
      return;
    }
    if (next == _current.text.trim()) {
      setState(() => _error = tr(context, 'newPinMustDiffer'));
      return;
    }

    final wrongPin = tr(context, 'currentPinWrong');
    final done = tr(context, 'pinChanged');
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.api.changePin(currentPin: _current.text.trim(), newPin: next);
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.status == 403 ? wrongPin : e.message);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr(context, 'changePin'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, T.s8),
        children: [
          Text(tr(context, 'changePinIntro'), style: T.body.copyWith(color: T.slate)),
          const SizedBox(height: T.s6),
          TextField(
            controller: _current,
            style: T.body,
            keyboardType: TextInputType.number,
            obscureText: true,
            maxLength: 4,
            decoration: InputDecoration(labelText: tr(context, 'currentPin'), counterText: ''),
          ),
          const SizedBox(height: T.s3),
          TextField(
            controller: _next,
            style: T.body,
            keyboardType: TextInputType.number,
            obscureText: true,
            maxLength: 4,
            decoration: InputDecoration(labelText: tr(context, 'newPin'), counterText: ''),
          ),
          const SizedBox(height: T.s3),
          TextField(
            controller: _nextAgain,
            style: T.body,
            keyboardType: TextInputType.number,
            obscureText: true,
            maxLength: 4,
            decoration: InputDecoration(labelText: tr(context, 'confirmPin'), counterText: ''),
            onSubmitted: (_) => _saving ? null : _save(),
          ),
          if (_error != null) ...[
            const SizedBox(height: T.s3),
            Invitation(icon: Icons.error_outline_rounded, message: _error!),
          ],
          const SizedBox(height: T.s4),
          FilledButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : Text(tr(context, 'saveChange')),
          ),
        ],
      ),
    );
  }
}
