import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';

import '../l10n/app_strings.dart';
import '../services/api_client.dart';
import '../theme/tokens.dart';
import '../widgets/status_group.dart';
import 'change_pin_screen.dart';

/// Her own record, and the one thing she can arrange without asking
/// anybody: cover while she is away.
///
/// Two things live here for the same reason -- both are facts about her
/// that the system already knew and had no way of telling her.
///
///   1. Her ASHA code. It is what a referral form and a block register
///      ask for, and until this screen existed the only way to learn it
///      was to ask somebody with dashboard access. Asking a supervisor
///      for your own staff number is an absurd errand.
///
///   2. Leave. Today an ASHA going away for a fortnight tells a
///      colleague verbally and the system never hears about it, so the
///      colleague cannot see those patients, cannot record what she
///      finds, and the ANM discovers the gap afterwards or not at all.
///
/// Cover is not a transfer. The patients stay hers; a named colleague
/// gains sight of them and the right to record visits for a stated
/// window, and it lapses on its own. That is what makes it safe to let
/// her arrange it herself -- which is the point, because a rule that
/// needs her ANM at a desk on a Friday is a rule she will route around.
class ProfileScreen extends StatefulWidget {
  final ApiClient api;

  /// Cover changes what her patient list contains, so the shell has to
  /// be told when it does.
  final VoidCallback? onChanged;

  /// Signing out tears down the whole navigation stack, which only the
  /// shell can do -- so it stays the shell's job and this screen just
  /// offers the button.
  final VoidCallback? onSignOut;

  const ProfileScreen({super.key, required this.api, this.onChanged, this.onSignOut});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late Future<Map<String, dynamic>> _profile;

  @override
  void initState() {
    super.initState();
    _profile = widget.api.fetchMyProfile();
  }

  /// [notify] tells the shell's tabs to refetch. Set only when cover
  /// changed, because that changes whose patients her list contains -- a
  /// plain "try again" after a network blip should not fire three extra
  /// requests behind her back.
  void _reload({bool notify = false}) {
    setState(() {
      _profile = widget.api.fetchMyProfile();
    });
    if (notify) widget.onChanged?.call();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: T.paper,
      appBar: AppBar(title: Text(tr(context, 'profile'))),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _profile,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError || snap.data == null) {
            return _RetryBody(onRetry: () => _reload());
          }
          return _ProfileBody(
            api: widget.api,
            profile: snap.data!,
            onChanged: () => _reload(notify: true),
            onSignOut: widget.onSignOut,
          );
        },
      ),
    );
  }
}

class _RetryBody extends StatelessWidget {
  final VoidCallback onRetry;
  const _RetryBody({required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(T.s6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              tr(context, 'failedToLoad'),
              textAlign: TextAlign.center,
              style: T.body,
            ),
            const SizedBox(height: T.s4),
            // The theme gives every outlined button Size.fromHeight(52),
            // which is an infinite minimum width -- correct for a button
            // that fills a form, wrong for one sitting alone in a Center,
            // where it would stretch across the screen.
            OutlinedButton(
              onPressed: onRetry,
              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 48)),
              child: Text(tr(context, 'tryAgain')),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProfileBody extends StatelessWidget {
  final ApiClient api;
  final Map<String, dynamic> profile;
  final VoidCallback onChanged;
  final VoidCallback? onSignOut;

  const _ProfileBody({
    required this.api,
    required this.profile,
    required this.onChanged,
    this.onSignOut,
  });

  @override
  Widget build(BuildContext context) {
    final code = profile['worker_code'] as String?;
    final absence = profile['my_absence'] as Map<String, dynamic>?;
    final covering = (profile['covering_for'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    final isAsha = (profile['role'] as String? ?? 'asha') == 'asha';

    return ListView(
      padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, T.s12),
      children: [
        _IdentityCard(profile: profile, code: code),
        const SizedBox(height: T.s6),
        _Counts(profile: profile),
        const SizedBox(height: T.s6),
        _SectionLabel(tr(context, 'mySubCentre')),
        StatusGroup(
          children: [
            StatusRow(
              railColour: T.slate,
              title: profile['sub_centre_id'] as String? ?? '—',
              subtitle: _joined(context, profile['joined_on'] as String?),
            ),
            StatusRow(
              railColour: T.indigo,
              title: tr(context, 'changePin'),
              subtitle: tr(context, 'changePinIntro'),
              trailing: const Icon(Icons.chevron_right, color: T.slate),
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => ChangePinScreen(api: api)),
              ),
            ),
          ],
        ),
        if (covering.isNotEmpty) ...[
          const SizedBox(height: T.s6),
          _SectionLabel(tr(context, 'coveringForSection')),
          StatusGroup(
            children: [
              for (final a in covering)
                StatusRow(
                  railColour: T.indigo,
                  title: a['worker_name'] as String? ?? '—',
                  subtitle: _window(a),
                  subtitleIsUrgent: a['in_effect'] == true,
                ),
            ],
          ),
        ],
        if (isAsha) ...[
          const SizedBox(height: T.s6),
          _SectionLabel(tr(context, 'leaveSection')),
          _LeavePanel(
            api: api,
            absence: absence,
            onChanged: onChanged,
          ),
        ],
        if (onSignOut != null) ...[
          const SizedBox(height: T.s8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: onSignOut,
              icon: const Icon(Icons.logout, size: 18),
              label: Text(tr(context, 'signOut')),
              style: OutlinedButton.styleFrom(foregroundColor: T.riskHigh),
            ),
          ),
        ],
      ],
    );
  }

  static String? _joined(BuildContext context, String? iso) {
    if (iso == null) return null;
    final when = DateTime.tryParse(iso);
    if (when == null) return null;
    return '${tr(context, 'registeredOn')} ${DateFormat.yMMMd().format(when.toLocal())}';
  }
}

/// The first letter of a name, by rune rather than by code unit.
///
/// `name[0]` splits a surrogate pair and renders a replacement box; the
/// names in this app are Devanagari, Tamil and Bengali as often as Latin,
/// so that is not a theoretical case.
String initialOf(String name) {
  final trimmed = name.trim();
  if (trimmed.isEmpty) return '?';
  return String.fromCharCode(trimmed.runes.first).toUpperCase();
}

String _window(Map<String, dynamic> a) {
  final from = DateTime.tryParse(a['starts_on'] as String? ?? '');
  final to = DateTime.tryParse(a['ends_on'] as String? ?? '');
  final fmt = DateFormat.MMMd();
  if (from == null || to == null) return '';
  return '${fmt.format(from)} – ${fmt.format(to)}';
}

class _SectionLabel extends StatelessWidget {
  final String text;
  const _SectionLabel(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: T.s3, left: T.s1),
      child: Text(text, style: T.section),
    );
  }
}

/// Her name, her role, and — the reason this screen exists — her code,
/// set large enough to read out over a phone line and tappable to copy.
class _IdentityCard extends StatelessWidget {
  final Map<String, dynamic> profile;
  final String? code;

  const _IdentityCard({required this.profile, required this.code});

  @override
  Widget build(BuildContext context) {
    final name = profile['name'] as String? ?? '';
    return Container(
      padding: const EdgeInsets.all(T.s4),
      decoration: BoxDecoration(
        color: T.surface,
        borderRadius: BorderRadius.circular(T.radius),
        border: Border.all(color: T.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              CircleAvatar(
                radius: 22,
                backgroundColor: T.sage,
                child: Text(
                  initialOf(name),
                  style: T.numeric(18).copyWith(color: T.forest),
                ),
              ),
              const SizedBox(width: T.s3),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name, style: T.title),
                    Text(_roleLabel(context, profile['role'] as String?), style: T.caption),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: T.s4),
          const Divider(height: 1, thickness: 1, color: T.hairline),
          const SizedBox(height: T.s4),
          Text(tr(context, 'myCode'), style: T.caption),
          const SizedBox(height: T.s1),
          // Copy rather than a "share" affordance: the realistic use is
          // reading it onto a paper form or into a WhatsApp message to
          // the block office, and a long code typed by hand from a
          // screen is a code typed wrong.
          InkWell(
            borderRadius: BorderRadius.circular(T.radius),
            onTap: code == null
                ? null
                : () {
                    Clipboard.setData(ClipboardData(text: code!));
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(code!)),
                    );
                  },
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: T.s1),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      code ?? '—',
                      style: T.numeric(24).copyWith(color: T.forest, letterSpacing: 0.5),
                    ),
                  ),
                  if (code != null)
                    const Icon(Icons.copy_rounded, size: 18, color: T.slate),
                ],
              ),
            ),
          ),
          const SizedBox(height: T.s2),
          Text(tr(context, 'myCodeHint'), style: T.caption),
        ],
      ),
    );
  }

  static String _roleLabel(BuildContext context, String? role) => switch (role) {
        'anm' => tr(context, 'roleAnm'),
        'bmo' => tr(context, 'roleBmo'),
        _ => tr(context, 'roleAsha'),
      };
}

class _Counts extends StatelessWidget {
  final Map<String, dynamic> profile;
  const _Counts({required this.profile});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _CountTile(
            value: '${profile['total_patients'] ?? 0}',
            label: tr(context, 'patientsInMyCare'),
          ),
        ),
        const SizedBox(width: T.s3),
        Expanded(
          child: _CountTile(
            value: '${profile['total_visits'] ?? 0}',
            label: tr(context, 'visitsRecorded'),
          ),
        ),
      ],
    );
  }
}

class _CountTile extends StatelessWidget {
  final String value;
  final String label;
  const _CountTile({required this.value, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(T.s4),
      decoration: BoxDecoration(
        color: T.surface,
        borderRadius: BorderRadius.circular(T.radius),
        border: Border.all(color: T.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(value, style: T.numeric(26)),
          const SizedBox(height: T.s1),
          Text(label, style: T.caption),
        ],
      ),
    );
  }
}

/// Either "you are away, and Kavita has your patients", or the form that
/// arranges that.
class _LeavePanel extends StatefulWidget {
  final ApiClient api;
  final Map<String, dynamic>? absence;
  final VoidCallback onChanged;

  const _LeavePanel({
    required this.api,
    required this.absence,
    required this.onChanged,
  });

  @override
  State<_LeavePanel> createState() => _LeavePanelState();
}

class _LeavePanelState extends State<_LeavePanel> {
  Future<List<Map<String, dynamic>>>? _colleagues;
  String? _coveringId;
  DateTime? _from;
  DateTime? _to;
  final _reason = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    if (widget.absence == null) _colleagues = widget.api.fetchColleagues();
  }

  @override
  void didUpdateWidget(covariant _LeavePanel old) {
    super.didUpdateWidget(old);
    // Cover just ended: the picker has to exist again, and the list it
    // needs was never fetched while the panel was in its "away" state.
    if (old.absence != null && widget.absence == null && _colleagues == null) {
      _colleagues = widget.api.fetchColleagues();
    }
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  Future<void> _pickDate({required bool start}) async {
    final today = DateTime.now();
    final initial = start ? (_from ?? today) : (_to ?? _from ?? today);
    final picked = await showDatePicker(
      context: context,
      initialDate: initial.isBefore(today) ? today : initial,
      firstDate: today,
      lastDate: today.add(const Duration(days: 365)),
    );
    if (picked == null) return;
    setState(() {
      if (start) {
        _from = picked;
        // A last day earlier than the first is not a choice she meant to
        // make; drop it rather than letting the server reject the form
        // after she has filled the rest of it in.
        if (_to != null && _to!.isBefore(picked)) _to = null;
      } else {
        _to = picked;
      }
      _error = null;
    });
  }

  Future<void> _save() async {
    if (_coveringId == null) {
      setState(() => _error = tr(context, 'pickAColleague'));
      return;
    }
    if (_from == null || _to == null) {
      // Naming the colleague she already chose would send her looking at
      // the one field she did fill in.
      setState(() => _error = tr(context, 'pickTheDates'));
      return;
    }
    final done = tr(context, 'leaveSet');
    final fallback = tr(context, 'couldNotSaveLeave');
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.declareLeave(
        coveringWorkerId: _coveringId!,
        startsOn: _from!,
        endsOn: _to!,
        reason: _reason.text.trim().isEmpty ? null : _reason.text.trim(),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
      widget.onChanged();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) setState(() => _error = fallback);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _end() async {
    final id = widget.absence?['absence_id'] as String?;
    if (id == null) return;
    final done = tr(context, 'leaveEnded');
    final fallback = tr(context, 'couldNotSaveLeave');
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.endLeave(id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
      widget.onChanged();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) setState(() => _error = fallback);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final absence = widget.absence;
    return Container(
      padding: const EdgeInsets.all(T.s4),
      decoration: BoxDecoration(
        color: T.surface,
        borderRadius: BorderRadius.circular(T.radius),
        border: Border.all(color: T.hairline),
      ),
      child: absence == null ? _form(context) : _away(context, absence),
    );
  }

  Widget _away(BuildContext context, Map<String, dynamic> absence) {
    final inEffect = absence['in_effect'] == true;
    final to = DateTime.tryParse(absence['ends_on'] as String? ?? '');
    final from = DateTime.tryParse(absence['starts_on'] as String? ?? '');
    final fmt = DateFormat.yMMMd();
    final headline = inEffect
        ? '${tr(context, 'leaveActive')} ${to == null ? '' : fmt.format(to)}'
        : '${tr(context, 'leaveBooked')} ${from == null ? '' : fmt.format(from)}';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(
              inEffect ? Icons.event_busy_rounded : Icons.event_available_rounded,
              size: 20,
              color: inEffect ? T.indigo : T.slate,
            ),
            const SizedBox(width: T.s2),
            Expanded(child: Text(headline, style: T.strong)),
          ],
        ),
        const SizedBox(height: T.s3),
        Text(
          '${tr(context, 'coveredBy')}: ${absence['covering_worker_name'] ?? '—'}'
          '${absence['covering_worker_code'] == null ? '' : ' (${absence['covering_worker_code']})'}',
          style: T.body,
        ),
        Text(_window(absence), style: T.caption),
        if ((absence['reason'] as String?)?.isNotEmpty == true) ...[
          const SizedBox(height: T.s2),
          Text(absence['reason'] as String, style: T.caption),
        ],
        if (_error != null) ...[
          const SizedBox(height: T.s3),
          Text(_error!, style: T.caption.copyWith(color: T.riskHigh)),
        ],
        const SizedBox(height: T.s4),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: _busy ? null : _end,
            icon: const Icon(Icons.how_to_reg_rounded, size: 18),
            label: Text(tr(context, 'endLeave')),
          ),
        ),
      ],
    );
  }

  Widget _form(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(tr(context, 'leaveIntro'), style: T.caption),
        const SizedBox(height: T.s4),
        FutureBuilder<List<Map<String, dynamic>>>(
          future: _colleagues,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const Padding(
                padding: EdgeInsets.symmetric(vertical: T.s3),
                child: LinearProgressIndicator(minHeight: 2),
              );
            }
            final list = snap.data ?? const <Map<String, dynamic>>[];
            if (list.isEmpty) {
              return Text(tr(context, 'noColleagues'), style: T.body);
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: _coveringId,
                  isExpanded: true,
                  decoration: InputDecoration(labelText: tr(context, 'whoWillCover')),
                  items: [
                    for (final c in list)
                      DropdownMenuItem(
                        value: c['worker_id'] as String,
                        child: Text(
                          c['worker_code'] == null
                              ? '${c['name']}'
                              : '${c['name']} · ${c['worker_code']}',
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                  onChanged: _busy ? null : (v) => setState(() => _coveringId = v),
                ),
                const SizedBox(height: T.s3),
                // Stacked, not side by side. Two date fields in a row on a
                // 320dp screen truncate to "First day a…" in every language
                // but English.
                _DateField(
                  label: tr(context, 'firstDayAway'),
                  value: _from,
                  onTap: _busy ? null : () => _pickDate(start: true),
                ),
                const SizedBox(height: T.s3),
                _DateField(
                  label: tr(context, 'lastDayAway'),
                  value: _to,
                  onTap: _busy ? null : () => _pickDate(start: false),
                ),
                const SizedBox(height: T.s3),
                TextField(
                  controller: _reason,
                  enabled: !_busy,
                  textInputAction: TextInputAction.done,
                  decoration: InputDecoration(labelText: tr(context, 'leaveReason')),
                ),
                if (_error != null) ...[
                  const SizedBox(height: T.s3),
                  Text(_error!, style: T.caption.copyWith(color: T.riskHigh)),
                ],
                const SizedBox(height: T.s4),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _busy ? null : _save,
                    child: _busy
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : Text(tr(context, 'declareLeave')),
                  ),
                ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _DateField extends StatelessWidget {
  final String label;
  final DateTime? value;
  final VoidCallback? onTap;

  const _DateField({required this.label, required this.value, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(T.radius),
      child: InputDecorator(
        decoration: InputDecoration(
          labelText: label,
          suffixIcon: const Icon(Icons.calendar_today_rounded, size: 18),
        ),
        child: Text(
          value == null ? '—' : DateFormat.yMMMd().format(value!),
          style: value == null ? T.body.copyWith(color: T.slate) : T.body,
        ),
      ),
    );
  }
}
