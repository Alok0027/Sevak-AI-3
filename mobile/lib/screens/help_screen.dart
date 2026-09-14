import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/app_strings.dart';
import '../services/api_client.dart';
import '../theme/tokens.dart';
import '../widgets/status_group.dart';
import 'change_pin_screen.dart';

/// Where an ASHA goes when the app has failed her.
///
/// Ordered by how fast each thing gets her unstuck, because she is
/// standing at somebody's door with a mother waiting:
///
///   1. A phone number. Her ANM answers in thirty seconds; nothing else
///      here competes with that.
///   2. The four questions that account for nearly every real problem --
///      readable with no signal, because the commonest problem *is* no
///      signal.
///   3. A report, which is slow for her but the only way anyone upstream
///      ever learns the app is failing in the field.
///
/// The EOI deck names user adoption as the top delivery risk and "training
/// & onboarding" as the mitigation. This screen and the tutorial are that
/// mitigation; without them the claim is a slide.
class HelpScreen extends StatefulWidget {
  final ApiClient api;

  /// Replays the first-run walkthrough. Passed in rather than triggered
  /// here because the tour points at controls that live in the shell.
  final VoidCallback? onReplayTutorial;

  const HelpScreen({super.key, required this.api, this.onReplayTutorial});

  @override
  State<HelpScreen> createState() => _HelpScreenState();
}

class _HelpScreenState extends State<HelpScreen> {
  late Future<List<Map<String, dynamic>>> _contactsFuture;
  Future<List<Map<String, dynamic>>>? _reportsFuture;
  int? _expandedFaq;

  @override
  void initState() {
    super.initState();
    _contactsFuture = _contactsOfflineFirst();
    _reportsFuture = widget.api.fetchMyReports();
  }

  /// The numbers have to survive having no signal.
  ///
  /// This screen is needed most in exactly the conditions that stop it
  /// loading: standing in a village with one bar, nothing working. Fetching
  /// the contacts fresh and showing "no supervisor number saved yet" when
  /// the request times out would put a lie on the screen at the moment she
  /// most needs a phone number.
  ///
  /// So: try the server, keep what it says, and fall back to the last
  /// answer it gave. A stale ANM number is worth a great deal more than an
  /// empty list.
  Future<List<Map<String, dynamic>>> _contactsOfflineFirst() async {
    try {
      final fresh = await widget.api.fetchSupportContacts();
      await _cacheContacts(fresh);
      return fresh;
    } catch (_) {
      return _cachedContacts();
    }
  }

  static const _kContactsCache = 'support_contacts_cache';

  Future<void> _cacheContacts(List<Map<String, dynamic>> contacts) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_kContactsCache, jsonEncode(contacts));
    } catch (_) {
      // Caching is a convenience. Failing to cache must never fail the
      // screen that just loaded perfectly well.
    }
  }

  Future<List<Map<String, dynamic>>> _cachedContacts() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_kContactsCache);
      if (raw == null) return const [];
      return (jsonDecode(raw) as List).cast<Map<String, dynamic>>();
    } catch (_) {
      return const [];
    }
  }

  Future<void> _refreshReports() async {
    final next = widget.api.fetchMyReports();
    setState(() {
      _reportsFuture = next;
    });
    try {
      await next;
    } catch (_) {
      // Shown by the FutureBuilder.
    }
  }

  Future<void> _open(Uri uri) async {
    final failed = tr(context, 'couldNotOpenApp');
    try {
      final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!ok && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(failed)));
      }
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(failed)));
    }
  }

  /// wa.me wants the number with a country code and no punctuation. Worker
  /// numbers are stored as ten digits, which is how they are written in
  /// India and how she would read one aloud -- so add +91 here rather than
  /// asking every admin to type it.
  String _whatsappNumber(String phone) {
    final digits = phone.replaceAll(RegExp(r'\D'), '');
    return digits.length == 10 ? '91$digits' : digits;
  }

  Future<void> _reportProblem() async {
    final sent = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: T.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(T.radius)),
      ),
      builder: (_) => _ReportSheet(api: widget.api),
    );
    if (sent == true) await _refreshReports();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr(context, 'help'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, T.s8),
        children: [
          Text(tr(context, 'helpIntro'), style: T.body.copyWith(color: T.slate)),
          const SizedBox(height: T.s6),

          // --- 1. Somebody to ring -------------------------------------
          FutureBuilder<List<Map<String, dynamic>>>(
            future: _contactsFuture,
            builder: (context, snapshot) {
              final contacts = snapshot.data ?? const [];
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const LinearProgressIndicator(minHeight: 2);
              }
              if (contacts.isEmpty) {
                return Invitation(
                  icon: Icons.phone_disabled_rounded,
                  message: tr(context, 'supervisorNotOnRecord'),
                );
              }
              return StatusGroup(
                children: [
                  for (final c in contacts)
                    StatusRow(
                      railColour: T.forest,
                      // Her supervisor's name is data -- never translated.
                      title: c['name'] as String,
                      subtitle: c['relationship'] == 'anm'
                          ? '${tr(context, 'callYourAnm')}  ·  ${c['phone']}'
                          : '${tr(context, 'help')}  ·  ${c['phone']}',
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            tooltip: tr(context, 'messageOnWhatsapp'),
                            icon: const Icon(Icons.chat_rounded, color: T.forest),
                            onPressed: () => _open(
                              Uri.parse('https://wa.me/${_whatsappNumber(c['phone'] as String)}'),
                            ),
                          ),
                          IconButton(
                            tooltip: tr(context, 'callYourAnm'),
                            icon: const Icon(Icons.phone_rounded, color: T.forest),
                            onPressed: () => _open(Uri(scheme: 'tel', path: c['phone'] as String)),
                          ),
                        ],
                      ),
                      onTap: () => _open(Uri(scheme: 'tel', path: c['phone'] as String)),
                    ),
                ],
              );
            },
          ),
          const SizedBox(height: T.s6),

          // --- 2. The four questions that cover almost everything -------
          SectionHeading(tr(context, 'commonQuestions')),
          StatusGroup(
            children: [
              for (int i = 0; i < _faqKeys.length; i++)
                _FaqRow(
                  question: tr(context, _faqKeys[i].$1),
                  answer: tr(context, _faqKeys[i].$2),
                  expanded: _expandedFaq == i,
                  onTap: () => setState(() => _expandedFaq = _expandedFaq == i ? null : i),
                ),
            ],
          ),
          const SizedBox(height: T.s6),

          // --- 3. Tell somebody it broke --------------------------------
          SectionHeading(tr(context, 'myReports')),
          FutureBuilder<List<Map<String, dynamic>>>(
            future: _reportsFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const LinearProgressIndicator(minHeight: 2);
              }
              final reports = snapshot.data ?? const [];
              if (reports.isEmpty) {
                return Invitation(
                  icon: Icons.inbox_rounded,
                  message: tr(context, 'noReportsYet'),
                );
              }
              return StatusGroup(
                children: [
                  for (final r in reports) _ReportRow(report: r),
                ],
              );
            },
          ),
          const SizedBox(height: T.s4),
          FilledButton.icon(
            onPressed: _reportProblem,
            icon: const Icon(Icons.report_problem_outlined),
            label: Text(tr(context, 'reportAProblem')),
          ),
          const SizedBox(height: T.s3),
          OutlinedButton.icon(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => ChangePinScreen(api: widget.api)),
            ),
            icon: const Icon(Icons.lock_reset_rounded),
            label: Text(tr(context, 'changePin')),
          ),
          const SizedBox(height: T.s3),
          OutlinedButton.icon(
            onPressed: widget.onReplayTutorial == null
                ? null
                : () {
                    Navigator.of(context).pop();
                    widget.onReplayTutorial!();
                  },
            icon: const Icon(Icons.school_outlined),
            label: Text(tr(context, 'showTutorialAgain')),
          ),
        ],
      ),
    );
  }
}

/// Question key, answer key. Ordered by how often each one actually
/// happens in the field, not by how interesting it is.
const _faqKeys = <(String, String)>[
  ('faqMicQ', 'faqMicA'),
  ('faqOfflineQ', 'faqOfflineA'),
  ('faqWrongTextQ', 'faqWrongTextA'),
  ('faqRiskQ', 'faqRiskA'),
];

class _FaqRow extends StatelessWidget {
  final String question;
  final String answer;
  final bool expanded;
  final VoidCallback onTap;

  const _FaqRow({
    required this.question,
    required this.answer,
    required this.expanded,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(T.s4, T.s3, T.s3, T.s3),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text(question, style: T.strong)),
                Icon(
                  expanded ? Icons.expand_less_rounded : Icons.expand_more_rounded,
                  color: T.slate,
                ),
              ],
            ),
            if (expanded) ...[
              const SizedBox(height: T.s2),
              Text(answer, style: T.body.copyWith(color: T.slate)),
            ],
          ],
        ),
      ),
    );
  }
}

class _ReportRow extends StatelessWidget {
  final Map<String, dynamic> report;
  const _ReportRow({required this.report});

  @override
  Widget build(BuildContext context) {
    final resolved = report['status'] == 'resolved';
    final created = DateTime.tryParse(report['created_at'] as String? ?? '');
    return Padding(
      padding: const EdgeInsets.fromLTRB(T.s4, T.s3, T.s4, T.s3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  // Her own words, in whatever language she typed them.
                  report['message'] as String? ?? '',
                  style: T.body,
                ),
              ),
              const SizedBox(width: T.s2),
              Text(
                tr(context, resolved ? 'statusResolved' : 'statusOpen'),
                style: T.micro.copyWith(
                  color: resolved ? T.forest : T.riskMedium,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          if (created != null) ...[
            const SizedBox(height: 2),
            Text(DateFormat.yMMMd().format(created.toLocal()), style: T.caption),
          ],
          if (resolved && (report['resolution_note'] as String?)?.isNotEmpty == true) ...[
            const SizedBox(height: T.s2),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(T.s2),
              decoration: BoxDecoration(
                color: T.sage,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(tr(context, 'supportReply'), style: T.micro.copyWith(color: T.forest)),
                  const SizedBox(height: 2),
                  Text(report['resolution_note'] as String, style: T.body),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// The report form. A sheet rather than a screen: it is one question and a
/// text box, and she should be able to back out of it with a swipe.
class _ReportSheet extends StatefulWidget {
  final ApiClient api;
  const _ReportSheet({required this.api});

  @override
  State<_ReportSheet> createState() => _ReportSheetState();
}

class _ReportSheetState extends State<_ReportSheet> {
  final _controller = TextEditingController();
  String _category = 'microphone';
  bool _sending = false;
  String? _error;

  /// Server-side keys paired with their label keys. The server files an
  /// unrecognised category under "other" rather than rejecting it, so a
  /// newer app can add to this list without waiting for a deploy.
  static const _categories = <(String, String)>[
    ('microphone', 'catMicrophone'),
    ('transcription', 'catTranscription'),
    ('sync', 'catSync'),
    ('login', 'catLogin'),
    ('risk', 'catRisk'),
    ('other', 'catOther'),
  ];

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.length < 5) {
      setState(() => _error = tr(context, 'writeALittleMore'));
      return;
    }
    final failed = tr(context, 'couldNotSendReport');
    final language = Localizations.localeOf(context).languageCode;
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      await widget.api.reportProblem(
        category: _category,
        message: text,
        appVersion: '0.1.0',
        // The first question support would otherwise have to ring her to
        // ask, filled in without her typing anything.
        deviceInfo: '${Platform.operatingSystem} ${Platform.operatingSystemVersion}',
        language: language,
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(tr(context, 'reportSent'))),
      );
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = failed);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
        T.s4,
        T.s4,
        T.s4,
        MediaQuery.of(context).viewInsets.bottom + T.s4,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(tr(context, 'whatIsWrong'), style: T.section),
          const SizedBox(height: T.s3),
          Wrap(
            spacing: T.s2,
            runSpacing: T.s2,
            children: [
              for (final (value, labelKey) in _categories)
                ChoiceChip(
                  label: Text(tr(context, labelKey), style: T.body),
                  selected: _category == value,
                  onSelected: (_) => setState(() => _category = value),
                  selectedColor: T.sage,
                  showCheckmark: false,
                ),
            ],
          ),
          const SizedBox(height: T.s4),
          TextField(
            controller: _controller,
            maxLines: 4,
            style: T.body,
            decoration: InputDecoration(
              hintText: tr(context, 'describeTheProblem'),
              hintStyle: T.body.copyWith(color: T.slate.withValues(alpha: 0.7)),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: T.s2),
            Text(_error!, style: T.caption.copyWith(color: T.riskHigh)),
          ],
          const SizedBox(height: T.s4),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: _sending ? null : _send,
              icon: _sending
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Icon(Icons.send_rounded),
              label: Text(tr(context, _sending ? 'sendingReport' : 'sendReport')),
            ),
          ),
        ],
      ),
    );
  }
}
