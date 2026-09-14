import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../l10n/app_strings.dart';
import '../models/history_models.dart';
import '../models/patient.dart';
import '../services/api_client.dart';
import '../theme/tokens.dart';
import '../widgets/status_group.dart';
import 'voice_record_screen.dart';

/// Who this patient is, then what has happened to her.
///
/// The identity block and her registration record come first, because an
/// ASHA opens this standing at a door: she needs the age, the village,
/// the phone number to ring if nobody answers, and the baseline readings
/// to compare today's against -- before any of the history matters. The
/// visit timeline (transcript + extracted record per visit, sourced from
/// GET /patients/{patient_id}/history) follows underneath.
class PatientDetailScreen extends StatefulWidget {
  final ApiClient api;
  final String patientId;
  final VoidCallback? onVisitRecorded;

  const PatientDetailScreen({
    super.key,
    required this.api,
    required this.patientId,
    this.onVisitRecorded,
  });

  @override
  State<PatientDetailScreen> createState() => _PatientDetailScreenState();
}

const _riskLevels = ['HIGH', 'MEDIUM', 'LOW'];

class _PatientDetailScreenState extends State<PatientDetailScreen> {
  late Future<PatientHistory> _future;
  int? _expandedIndex;

  // FR-03.3: risk override -- which visit's inline form is open, plus that
  // form's own state. Only one can be open at a time, mirroring the
  // expand/collapse pattern already used for the extracted-record view.
  String? _overridingVisitId;
  String _overrideLevel = 'MEDIUM';
  final _reasonController = TextEditingController();
  bool _overrideSubmitting = false;
  String? _overrideError;

  @override
  void initState() {
    super.initState();
    _future = widget.api.fetchPatientHistory(widget.patientId);
  }

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    final next = widget.api.fetchPatientHistory(widget.patientId);
    setState(() {
      _future = next;
      _expandedIndex = null;
    });
    await next;
  }

  void _startOverride(VisitEntry visit) {
    setState(() {
      _overridingVisitId = visit.visitId;
      _overrideLevel = _riskLevels.firstWhere((l) => l != visit.riskLevel, orElse: () => 'MEDIUM');
      _reasonController.clear();
      _overrideError = null;
    });
  }

  void _cancelOverride() {
    setState(() {
      _overridingVisitId = null;
      _overrideError = null;
    });
  }

  Future<void> _submitOverride(String visitId) async {
    if (_reasonController.text.trim().length < 5) {
      setState(() => _overrideError = tr(context, 'giveAReason'));
      return;
    }
    final saveFailed = tr(context, 'couldNotSaveCorrection');
    setState(() {
      _overrideSubmitting = true;
      _overrideError = null;
    });
    try {
      await widget.api.overrideRisk(
        visitId: visitId,
        newRiskLevel: _overrideLevel,
        reason: _reasonController.text.trim(),
      );
      if (!mounted) return;
      setState(() => _overridingVisitId = null);
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      setState(() => _overrideError = '$saveFailed: $e');
    } finally {
      if (mounted) setState(() => _overrideSubmitting = false);
    }
  }

  Future<void> _recordVisit(PatientHistory data) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => VoiceRecordScreen(
          api: widget.api,
          workerId: data.workerId,
          patient: Patient(id: data.patientId, name: data.patientName),
        ),
      ),
    );
    widget.onVisitRecorded?.call();
    _refresh();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr(context, 'patientHistory'))),
      body: RefreshIndicator(
        color: T.forest,
        onRefresh: _refresh,
        child: FutureBuilder<PatientHistory>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator(color: T.forest));
            }
            if (snapshot.hasError) {
              return ListView(
                padding: const EdgeInsets.all(T.s4),
                children: [
                  const SizedBox(height: T.s12),
                  Invitation(
                    icon: Icons.wifi_off_rounded,
                    message: '${tr(context, 'failedToLoad')}: ${snapshot.error}',
                  ),
                ],
              );
            }
            final data = snapshot.data!;
            return ListView(
              padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, 96),
              children: [
                _Identity(data: data),
                const SizedBox(height: T.s6),
                SectionHeading(tr(context, 'patientDetails')),
                _DetailsCard(data: data),
                const SizedBox(height: T.s6),
                SectionHeading(
                  tr(context, 'visitTimeline'),
                  trailing: '${data.visits.length}',
                ),
                if (data.visits.isEmpty)
                  Invitation(icon: Icons.mic_none_rounded, message: tr(context, 'noVisitsRecorded'))
                else
                  for (int i = 0; i < data.visits.length; i++) ...[
                    if (i > 0) const SizedBox(height: T.s2),
                    _VisitTile(
                      visit: data.visits[i],
                      expanded: _expandedIndex == i,
                      onTap: () => setState(() => _expandedIndex = _expandedIndex == i ? null : i),
                      isOverriding: _overridingVisitId == data.visits[i].visitId,
                      onStartOverride: () => _startOverride(data.visits[i]),
                      onCancelOverride: _cancelOverride,
                      onSubmitOverride: () => _submitOverride(data.visits[i].visitId),
                      overrideLevel: _overrideLevel,
                      onOverrideLevelChanged: (v) => setState(() => _overrideLevel = v),
                      reasonController: _reasonController,
                      overrideSubmitting: _overrideSubmitting,
                      overrideError: _overrideError,
                    ),
                  ],
              ],
            );
          },
        ),
      ),
      floatingActionButton: FutureBuilder<PatientHistory>(
        future: _future,
        builder: (context, snapshot) {
          if (!snapshot.hasData) return const SizedBox.shrink();
          final data = snapshot.data!;
          return FloatingActionButton.extended(
            backgroundColor: T.forest,
            foregroundColor: Colors.white,
            icon: const Icon(Icons.mic),
            label: Text(tr(context, 'recordVisit'), style: T.strong.copyWith(color: Colors.white)),
            onPressed: () => _recordVisit(data),
          );
        },
      ),
    );
  }
}

/// Name, initials, and the one-line summary an ASHA repeats to herself on
/// the way to the door. The name is shown exactly as it was registered --
/// it is data, not interface, so it never gets translated.
class _Identity extends StatelessWidget {
  final PatientHistory data;
  const _Identity({required this.data});

  @override
  Widget build(BuildContext context) {
    final initials = data.patientName
        .split(' ')
        .where((p) => p.isNotEmpty)
        .map((p) => p[0])
        .take(2)
        .join()
        .toUpperCase();
    final summary = [
      if (data.age != null) '${data.age} ${tr(context, 'years')}',
      if (data.village != null && data.village!.isNotEmpty) data.village!,
      if (data.pregnancyStage != null && data.pregnancyStage!.isNotEmpty)
        '${data.pregnancyStage} ${tr(context, 'pregnant')}',
    ].join('  ·  ');

    return Row(
      children: [
        Container(
          width: 56,
          height: 56,
          alignment: Alignment.center,
          decoration: const BoxDecoration(color: T.sage, shape: BoxShape.circle),
          child: Text(initials, style: T.numeric(18).copyWith(color: T.forest)),
        ),
        const SizedBox(width: T.s3),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(data.patientName, style: T.title),
              if (summary.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(summary, style: T.caption),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

/// The registration record, as a labelled grid rather than prose.
///
/// Shows every field including the ones nobody filled in, marked "not
/// recorded" -- a blank row is information (nobody has taken her blood
/// pressure yet), whereas hiding the row makes the gap invisible and the
/// card look complete when it isn't.
class _DetailsCard extends StatelessWidget {
  final PatientHistory data;
  const _DetailsCard({required this.data});

  @override
  Widget build(BuildContext context) {
    final missing = tr(context, 'notRecorded');
    final bp = data.hasBloodPressure ? '${data.bpSystolic}/${data.bpDiastolic} mmHg' : missing;
    final sugar = data.hasBloodSugar
        ? [
            if (data.bloodSugarFasting != null)
              '${data.bloodSugarFasting} (${tr(context, 'fasting')})',
            if (data.bloodSugarRandom != null)
              '${data.bloodSugarRandom} (${tr(context, 'random')})',
          ].join('  ·  ')
        : missing;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: T.s4, vertical: T.s3),
      decoration: BoxDecoration(
        color: T.surface,
        borderRadius: BorderRadius.circular(T.radius),
        border: Border.all(color: T.hairline),
      ),
      child: Column(
        children: [
          _Field(tr(context, 'age'), data.age == null ? missing : '${data.age}'),
          _Field(tr(context, 'gender'), _blankToMissing(data.gender, missing)),
          _Field(tr(context, 'village'), _blankToMissing(data.village, missing)),
          _Field(tr(context, 'phone'), _blankToMissing(data.phone, missing)),
          _Field(tr(context, 'pregnancyStage'), _blankToMissing(data.pregnancyStage, missing)),
          // Baselines last and visually grouped: they are the readings
          // today's measurement gets compared against, so they belong
          // together rather than scattered among the identity fields.
          const Divider(height: T.s4, thickness: 1, color: T.hairline),
          _Field(tr(context, 'bloodPressure'), bp),
          _Field(tr(context, 'bloodSugar'), sugar),
          const Divider(height: T.s4, thickness: 1, color: T.hairline),
          _Field(tr(context, 'ashaWorker'), data.workerName),
          _Field(
            tr(context, 'registeredOn'),
            data.registeredAt == null
                ? missing
                : DateFormat.yMMMd().format(data.registeredAt!.toLocal()),
          ),
        ],
      ),
    );
  }

  static String _blankToMissing(String? value, String missing) =>
      (value == null || value.trim().isEmpty) ? missing : value;
}

class _Field extends StatelessWidget {
  final String label;
  final String value;
  const _Field(this.label, this.value);

  @override
  Widget build(BuildContext context) {
    final isMissing = value == tr(context, 'notRecorded');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 132, child: Text(label, style: T.caption)),
          Expanded(
            child: Text(
              value,
              style: isMissing
                  ? T.body.copyWith(color: T.slate.withValues(alpha: 0.7))
                  : T.strong,
            ),
          ),
        ],
      ),
    );
  }
}

class _VisitTile extends StatelessWidget {
  final VisitEntry visit;
  final bool expanded;
  final VoidCallback onTap;

  // FR-03.3: risk override -- all state lives in the parent screen (only
  // one tile's form can be open at once), this widget just renders it.
  final bool isOverriding;
  final VoidCallback onStartOverride;
  final VoidCallback onCancelOverride;
  final VoidCallback onSubmitOverride;
  final String overrideLevel;
  final ValueChanged<String> onOverrideLevelChanged;
  final TextEditingController reasonController;
  final bool overrideSubmitting;
  final String? overrideError;

  const _VisitTile({
    required this.visit,
    required this.expanded,
    required this.onTap,
    required this.isOverriding,
    required this.onStartOverride,
    required this.onCancelOverride,
    required this.onSubmitOverride,
    required this.overrideLevel,
    required this.onOverrideLevelChanged,
    required this.reasonController,
    required this.overrideSubmitting,
    required this.overrideError,
  });

  @override
  Widget build(BuildContext context) {
    final extracted = visit.extracted;
    final colour = T.risk(visit.riskLevel);

    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: T.surface,
        borderRadius: BorderRadius.circular(T.radius),
        border: Border.all(color: T.hairline),
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Same status rail as every other list in the product.
            Container(width: 3, color: colour),
            Expanded(
              child: InkWell(
                onTap: onTap,
                child: Padding(
                  padding: const EdgeInsets.all(T.s3),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              DateFormat.yMMMd().add_jm().format(visit.createdAt.toLocal()),
                              style: T.strong,
                            ),
                          ),
                          Text(
                            visit.riskLevel ?? '—',
                            style: T.micro.copyWith(color: colour, fontWeight: FontWeight.w700),
                          ),
                        ],
                      ),
                      if (visit.transcript != null && visit.transcript!.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: T.s1),
                          child: Text('“${visit.transcript}”', style: T.body.copyWith(color: T.slate)),
                        ),
                      if (visit.riskOverridden) ...[
                        const SizedBox(height: T.s2),
                        // Indigo, per the token rule: a human decided this.
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(T.s2),
                          decoration: BoxDecoration(
                            color: T.indigo.withValues(alpha: 0.06),
                            borderRadius: BorderRadius.circular(6),
                            border: Border.all(color: T.indigo.withValues(alpha: 0.25)),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${tr(context, 'correctedBy')} '
                                '${visit.overriddenByName ?? tr(context, 'aSupervisor')}'
                                '${visit.overriddenByRole != null ? ' (${visit.overriddenByRole!.toUpperCase()})' : ''}',
                                style: T.micro.copyWith(color: T.indigo),
                              ),
                              if (visit.riskOverrideReason != null)
                                Padding(
                                  padding: const EdgeInsets.only(top: 2),
                                  child: Text(
                                    '${tr(context, 'reasonLabel')}: “${visit.riskOverrideReason}”',
                                    style: T.caption,
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ],
                      if (!isOverriding)
                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton(
                            onPressed: onStartOverride,
                            style: TextButton.styleFrom(
                              padding: EdgeInsets.zero,
                              minimumSize: const Size(0, 36),
                              foregroundColor: T.indigo,
                            ),
                            child: Text(
                              tr(context, 'overrideRiskLevel'),
                              style: T.caption.copyWith(color: T.indigo, fontWeight: FontWeight.w600),
                            ),
                          ),
                        ),
                      if (isOverriding)
                        _OverrideForm(
                          currentLevel: visit.riskLevel,
                          overrideLevel: overrideLevel,
                          onOverrideLevelChanged: onOverrideLevelChanged,
                          reasonController: reasonController,
                          overrideSubmitting: overrideSubmitting,
                          overrideError: overrideError,
                          onCancel: onCancelOverride,
                          onSubmit: onSubmitOverride,
                        ),
                      if (expanded && extracted != null) ...[
                        const Divider(height: T.s4, thickness: 1, color: T.hairline),
                        for (final entry in extracted.entries)
                          if (entry.key != 'confidence_scores' &&
                              entry.value != null &&
                              entry.value.toString().isNotEmpty)
                            Padding(
                              padding: const EdgeInsets.symmetric(vertical: 2),
                              child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  SizedBox(
                                    width: 132,
                                    child: Text(entry.key.replaceAll('_', ' '), style: T.caption),
                                  ),
                                  Expanded(
                                    child: Text(
                                      entry.value is List
                                          ? (entry.value as List).join(', ')
                                          : entry.value.toString(),
                                      style: T.strong,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                      ],
                      Align(
                        alignment: Alignment.centerRight,
                        child: Text(
                          expanded ? tr(context, 'tapToCollapse') : tr(context, 'tapForFullRecord'),
                          style: T.micro.copyWith(color: T.slate, fontWeight: FontWeight.w500),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OverrideForm extends StatelessWidget {
  final String? currentLevel;
  final String overrideLevel;
  final ValueChanged<String> onOverrideLevelChanged;
  final TextEditingController reasonController;
  final bool overrideSubmitting;
  final String? overrideError;
  final VoidCallback onCancel;
  final VoidCallback onSubmit;

  const _OverrideForm({
    required this.currentLevel,
    required this.overrideLevel,
    required this.onOverrideLevelChanged,
    required this.reasonController,
    required this.overrideSubmitting,
    required this.overrideError,
    required this.onCancel,
    required this.onSubmit,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: T.s2),
      padding: const EdgeInsets.all(T.s3),
      decoration: BoxDecoration(
        color: T.paper,
        borderRadius: BorderRadius.circular(T.radius),
        border: Border.all(color: T.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(tr(context, 'correctRiskLevelTo'), style: T.caption),
          const SizedBox(height: T.s1),
          DropdownButtonFormField<String>(
            initialValue: overrideLevel,
            isDense: true,
            borderRadius: BorderRadius.circular(T.radius),
            decoration: const InputDecoration(isDense: true),
            items: _riskLevels
                .map((l) => DropdownMenuItem(
                      value: l,
                      enabled: l != currentLevel,
                      child: Text(
                        l == currentLevel ? '$l (${tr(context, 'currentNoChange')})' : l,
                        style: T.body.copyWith(
                          color: l == currentLevel ? T.slate : T.risk(l),
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ))
                .toList(),
            onChanged: (v) {
              if (v != null) onOverrideLevelChanged(v);
            },
          ),
          const SizedBox(height: T.s3),
          Text(tr(context, 'reasonForCorrection'), style: T.caption),
          const SizedBox(height: T.s1),
          TextField(
            controller: reasonController,
            maxLines: 3,
            style: T.body,
            decoration: InputDecoration(
              isDense: true,
              hintText: tr(context, 'reasonHint'),
              hintStyle: T.body.copyWith(color: T.slate.withValues(alpha: 0.7)),
            ),
          ),
          if (overrideError != null)
            Padding(
              padding: const EdgeInsets.only(top: T.s2),
              child: Text(overrideError!, style: T.caption.copyWith(color: T.riskHigh)),
            ),
          const SizedBox(height: T.s3),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                onPressed: overrideSubmitting ? null : onCancel,
                child: Text(tr(context, 'cancel')),
              ),
              const SizedBox(width: T.s1),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: T.indigo,
                  minimumSize: const Size(0, 44),
                  padding: const EdgeInsets.symmetric(horizontal: T.s4),
                ),
                onPressed: overrideSubmitting ? null : onSubmit,
                child: overrideSubmitting
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : Text(tr(context, 'saveCorrection')),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
