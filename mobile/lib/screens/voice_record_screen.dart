import 'dart:convert';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../l10n/app_strings.dart';
import '../models/patient.dart';
import '../services/api_client.dart';
import '../services/offline_queue.dart';
import '../theme/tokens.dart';

/// FR-01.1/01.3/01.4: record a home-visit voice note, then review it in two
/// passes before anything downstream runs (risk scoring, referral drafting,
/// HMIS reporting).
///
/// First the transcript, so a mishearing is a quick text edit rather than a
/// silently-wrong record. Then the clinical fields pulled out of it, because
/// a misheard "140 over 90" doesn't just read wrong -- it *is* the input to
/// the risk classification, and correcting it after the fact means
/// overriding a risk level instead of preventing a wrong one.
///
/// Submits immediately if online, or queues it for automatic sync if
/// offline (the offline path skips review entirely, since there's no
/// server to transcribe against until connectivity returns).
class VoiceRecordScreen extends StatefulWidget {
  final ApiClient api;
  final String workerId;
  final Patient patient;

  const VoiceRecordScreen({super.key, required this.api, required this.workerId, required this.patient});

  @override
  State<VoiceRecordScreen> createState() => _VoiceRecordScreenState();
}

class _VoiceRecordScreenState extends State<VoiceRecordScreen> {
  final _recorder = AudioRecorder();
  final _queue = OfflineQueue();
  final _transcriptController = TextEditingController();

  bool _isRecording = false;
  bool _isTranscribing = false;
  bool _isExtracting = false;
  bool _isSubmitting = false;
  bool _isReviewing = false;
  bool _isReviewingFields = false;
  String? _speechLanguage; // null = follow the app's UI language
  String? _recordedPath;
  String? _pendingAudioBase64; // kept around for the offline-fallback path
  Map<String, dynamic>? _result;
  String? _statusMessage;

  /// Whatever Agent 1 extracted, kept whole so fields the form doesn't show
  /// (patient_name, age, social_risk_factors) survive the round trip
  /// instead of being blanked out by what we send back.
  Map<String, dynamic> _extracted = {};
  final _bpSystolicController = TextEditingController();
  final _bpDiastolicController = TextEditingController();
  final _temperatureController = TextEditingController();
  final _weightController = TextEditingController();
  final _pregnancyController = TextEditingController();
  final _sugarFastingController = TextEditingController();
  final _sugarRandomController = TextEditingController();
  String _medicationCompliance = 'unknown';

  /// The language the *visit* is conducted in, which is not necessarily
  /// the one the app is showing -- an ASHA may read the interface in
  /// Hindi and take a history in Marathi. Defaults to the UI language and
  /// stays changeable; each option is written in its own script.
  static const _speechLanguages = {
    'hi': 'हिन्दी',
    'mr': 'मराठी',
    'ta': 'தமிழ்',
    'te': 'తెలుగు',
    'bn': 'বাংলা',
  };

  String get _languageCode {
    if (_speechLanguage != null) return _speechLanguage!;
    final ui = Localizations.localeOf(context).languageCode;
    return _speechLanguages.containsKey(ui) ? ui : 'hi';
  }

  static Map<String, String> _complianceLabels(BuildContext context) => {
        'compliant': tr(context, 'takingMedication'),
        'non_compliant': tr(context, 'notTakingMedication'),
        'unknown': tr(context, 'notMentioned'),
      };

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: T.riskHigh),
    );
  }

  Future<void> _toggleRecording() async {
    // Read before the first await: past that point the widget may be gone.
    final micMessage = tr(context, 'micDenied');
    final startFailed = tr(context, 'couldNotStartRecording');
    try {
      if (_isRecording) {
        final path = await _recorder.stop();
        setState(() {
          _isRecording = false;
          _recordedPath = path;
        });
        return;
      }
      final hasPermission = await _recorder.hasPermission();
      if (!hasPermission) {
        _showError(micMessage);
        return;
      }
      final dir = await getTemporaryDirectory();
      final path = '${dir.path}/visit_${DateTime.now().millisecondsSinceEpoch}.m4a';
      // Compressed AAC on purpose: an ASHA uploads these over a rural mobile
      // connection, and the same clip is roughly 10x smaller than raw WAV.
      // The server converts to the 16kHz mono WAV Bhashini's ASR wants
      // (to_wav_16k_mono in app/services/bhashini_client.py). Asking for
      // AudioEncoder.wav here doesn't help anyway -- Android falls back to
      // the platform recorder and returns AAC in an MP4 container regardless.
      await _recorder.start(const RecordConfig(), path: path);
      setState(() {
        _isRecording = true;
        _isReviewing = false;
        _isReviewingFields = false;
        _result = null;
        _statusMessage = null;
      });
    } catch (e) {
      // Never let a mic failure look like an unresponsive button -- always
      // surface exactly what went wrong (permission plugin error, no mic
      // hardware, browser blocking access, etc).
      setState(() => _isRecording = false);
      _showError('$startFailed: $e');
    }
  }

  /// Step 1: transcribe the recording and show it for review, instead of
  /// running it straight through the pipeline (FR-01.4).
  Future<void> _reviewTranscript() async {
    if (_recordedPath == null) return;
    // Read every context-dependent value up front. Everything below this
    // line runs after an await, where the widget may already be gone.
    final language = _languageCode;
    final offlineMessage = tr(context, 'offlineSaved');
    final unreachableMessage = tr(context, 'couldNotReachServer');
    setState(() {
      _isTranscribing = true;
      _statusMessage = null;
    });

    final bytes = await File(_recordedPath!).readAsBytes();
    final audioBase64 = base64Encode(bytes);
    _pendingAudioBase64 = audioBase64;

    try {
      final connectivity = await Connectivity().checkConnectivity();
      final online = !connectivity.contains(ConnectivityResult.none);
      if (!online) {
        // No server to transcribe against -- queue the raw recording as
        // before; it'll be transcribed fresh when sync runs (FR-07.1).
        await _queue.enqueueVisit(
          workerId: widget.workerId,
          patientId: widget.patient.id,
          audioBase64: audioBase64,
          languageCode: language,
        );
        setState(() => _statusMessage = offlineMessage);
        return;
      }

      final transcript =
          await widget.api.transcribeAudio(audioBase64: audioBase64, languageCode: language);
      setState(() {
        _transcriptController.text = transcript;
        _isReviewing = true;
      });
    } catch (e) {
      // Couldn't even reach the server to transcribe -- fall back to the
      // offline queue rather than losing the visit (FR-07.1).
      await _queue.enqueueVisit(
        workerId: widget.workerId,
        patientId: widget.patient.id,
        audioBase64: audioBase64,
        languageCode: language,
      );
      setState(() => _statusMessage = '$unreachableMessage ($e)');
    } finally {
      if (mounted) setState(() => _isTranscribing = false);
    }
  }

  /// Step 2: read the clinical fields out of the transcript she just
  /// approved, and show them for correction. Deliberately extracted from
  /// the *confirmed* text, not the original audio, so the fields can never
  /// contradict the transcript she's looking at.
  Future<void> _reviewFields() async {
    final edited = _transcriptController.text.trim();
    if (edited.isEmpty) {
      _showError(tr(context, 'transcriptEmpty'));
      return;
    }
    final readFailed = tr(context, 'couldNotReadDetails');
    setState(() {
      _isExtracting = true;
      _statusMessage = null;
    });
    try {
      final extracted = await widget.api.extractFields(transcript: edited);
      setState(() {
        _extracted = extracted;
        _bpSystolicController.text = extracted['bp_systolic']?.toString() ?? '';
        _bpDiastolicController.text = extracted['bp_diastolic']?.toString() ?? '';
        _temperatureController.text = extracted['temperature_c']?.toString() ?? '';
        _weightController.text = extracted['weight_kg']?.toString() ?? '';
        _pregnancyController.text = (extracted['pregnancy_stage'] as String?) ?? '';
        _sugarFastingController.text = extracted['blood_sugar_fasting']?.toString() ?? '';
        _sugarRandomController.text = extracted['blood_sugar_random']?.toString() ?? '';
        _medicationCompliance = (extracted['medication_compliance'] as String?) ?? 'unknown';
        _isReviewing = false;
        _isReviewingFields = true;
      });
    } catch (e) {
      _showError('$readFailed: $e');
    } finally {
      if (mounted) setState(() => _isExtracting = false);
    }
  }

  /// Step 3: submit exactly the text *and* the field values she reviewed --
  /// never a fresh re-transcription or re-extraction, which could differ
  /// from what she approved.
  Future<void> _confirmAndSubmit() async {
    final edited = _transcriptController.text.trim();
    if (edited.isEmpty) {
      _showError(tr(context, 'transcriptEmpty'));
      return;
    }
    final language = _languageCode;
    final unreachableMessage = tr(context, 'couldNotReachServer');
    final submitFailed = tr(context, 'couldNotSubmit');
    setState(() {
      _isSubmitting = true;
      _statusMessage = null;
    });
    try {
      final pregnancy = _pregnancyController.text.trim();
      final confirmed = Map<String, dynamic>.from(_extracted)
        ..['bp_systolic'] = int.tryParse(_bpSystolicController.text.trim())
        ..['bp_diastolic'] = int.tryParse(_bpDiastolicController.text.trim())
        ..['temperature_c'] = double.tryParse(_temperatureController.text.trim())
        ..['weight_kg'] = double.tryParse(_weightController.text.trim())
        ..['pregnancy_stage'] = pregnancy.isEmpty ? null : pregnancy
        ..['blood_sugar_fasting'] = int.tryParse(_sugarFastingController.text.trim())
        ..['blood_sugar_random'] = int.tryParse(_sugarRandomController.text.trim())
        ..['medication_compliance'] = _medicationCompliance;

      final result = await widget.api.submitVoiceVisit(
        workerId: widget.workerId,
        patientId: widget.patient.id,
        languageCode: language,
        confirmedTranscript: edited,
        confirmedExtracted: confirmed,
      );
      setState(() {
        _result = result;
        _isReviewing = false;
        _isReviewingFields = false;
      });
    } catch (e) {
      // Network dropped between review and confirm -- fall back to queuing
      // the original audio so the visit isn't lost. Note this does mean
      // her edits don't carry through to the eventual sync (it'll be
      // freshly re-transcribed then); a rare edge case worth accepting
      // rather than losing the visit entirely.
      if (_pendingAudioBase64 != null) {
        await _queue.enqueueVisit(
          workerId: widget.workerId,
          patientId: widget.patient.id,
          audioBase64: _pendingAudioBase64!,
          languageCode: language,
        );
        setState(() {
          _statusMessage = '$unreachableMessage ($e)';
          _isReviewing = false;
          _isReviewingFields = false;
        });
      } else {
        _showError('$submitFailed: $e');
      }
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  void _reRecord() {
    setState(() {
      _isReviewing = false;
      _isReviewingFields = false;
      _recordedPath = null;
      _pendingAudioBase64 = null;
      _transcriptController.clear();
      _extracted = {};
    });
  }

  @override
  void dispose() {
    _recorder.dispose();
    _transcriptController.dispose();
    _bpSystolicController.dispose();
    _bpDiastolicController.dispose();
    _temperatureController.dispose();
    _weightController.dispose();
    _pregnancyController.dispose();
    _sugarFastingController.dispose();
    _sugarRandomController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // Her name, as registered -- this screen is about a person, and the
      // name is data, so it is never translated.
      appBar: AppBar(title: Text(widget.patient.name)),
      body: Padding(
        padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, T.s4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_isReviewingFields)
              ..._fieldReview(context)
            else if (_isReviewing)
              ..._transcriptReview(context)
            else
              ..._recordStep(context),
            if (_statusMessage != null)
              Padding(
                padding: const EdgeInsets.only(top: T.s3),
                child: Text(_statusMessage!, style: T.caption.copyWith(color: T.riskMedium)),
              ),
            if (_result != null) ...[
              const Divider(height: T.s8, thickness: 1, color: T.hairline),
              _ResultPanel(result: _result!),
            ],
          ],
        ),
      ),
    );
  }

  /// Step 0 -- the recorder itself.
  List<Widget> _recordStep(BuildContext context) => [
        DropdownButtonFormField<String>(
          value: _languageCode,
          borderRadius: BorderRadius.circular(T.radius),
          decoration: InputDecoration(labelText: tr(context, 'language')),
          items: _speechLanguages.entries
              .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value, style: T.body)))
              .toList(),
          onChanged: (v) => setState(() => _speechLanguage = v),
        ),
        const SizedBox(height: T.s8),
        Center(
          child: Semantics(
            button: true,
            label: tr(context, _isRecording ? 'recordingTapToStop' : 'tapToRecord'),
            child: InkWell(
              onTap: _toggleRecording,
              customBorder: const CircleBorder(),
              child: Container(
                width: 104,
                height: 104,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: _isRecording ? T.riskHigh : T.forest,
                  shape: BoxShape.circle,
                ),
                child: Icon(_isRecording ? Icons.stop : Icons.mic, size: 44, color: Colors.white),
              ),
            ),
          ),
        ),
        const SizedBox(height: T.s3),
        Center(
          child: Text(
            tr(context, _isRecording ? 'recordingTapToStop' : 'tapToRecord'),
            style: T.body.copyWith(color: T.slate),
          ),
        ),
        const SizedBox(height: T.s6),
        if (_recordedPath != null && !_isRecording)
          FilledButton.icon(
            onPressed: _isTranscribing ? null : _reviewTranscript,
            icon: _isTranscribing
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Icon(Icons.hearing),
            label: Text(tr(context, _isTranscribing ? 'transcribing' : 'reviewWhatWasHeard')),
          ),
      ];

  /// Step 1 -- the transcript, before anything downstream runs (FR-01.4).
  List<Widget> _transcriptReview(BuildContext context) => [
        Text(tr(context, 'isThisWhatYouSaid'), style: T.section),
        const SizedBox(height: T.s1),
        Text(tr(context, 'fixAnythingHeardWrong'), style: T.caption),
        const SizedBox(height: T.s3),
        Expanded(
          child: TextField(
            controller: _transcriptController,
            maxLines: null,
            expands: true,
            textAlignVertical: TextAlignVertical.top,
            // In the language she spoke. Shown as heard, never translated.
            style: T.body,
            decoration: const InputDecoration(contentPadding: EdgeInsets.all(T.s3)),
          ),
        ),
        const SizedBox(height: T.s3),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _isExtracting ? null : _reRecord,
                icon: const Icon(Icons.mic),
                label: Text(tr(context, 'reRecord')),
              ),
            ),
            const SizedBox(width: T.s3),
            Expanded(
              child: FilledButton.icon(
                onPressed: _isExtracting ? null : _reviewFields,
                icon: _isExtracting
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.arrow_forward),
                label: Text(tr(context, _isExtracting ? 'reading' : 'nextCheckDetails')),
              ),
            ),
          ],
        ),
      ];

  /// Step 2 -- the clinical fields, which *are* the risk input. A misheard
  /// "140 over 90" corrected here prevents a wrong risk level; corrected
  /// afterwards it means overriding one.
  List<Widget> _fieldReview(BuildContext context) => [
        Text(tr(context, 'checkTheDetails'), style: T.section),
        const SizedBox(height: T.s1),
        Text(tr(context, 'detailsFromSpeech'), style: T.caption),
        const SizedBox(height: T.s3),
        Expanded(
          child: ListView(
            children: [
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _bpSystolicController,
                      keyboardType: TextInputType.number,
                      style: T.body,
                      decoration: InputDecoration(labelText: tr(context, 'bpUpper')),
                    ),
                  ),
                  const SizedBox(width: T.s3),
                  Expanded(
                    child: TextField(
                      controller: _bpDiastolicController,
                      keyboardType: TextInputType.number,
                      style: T.body,
                      decoration: InputDecoration(labelText: tr(context, 'bpLower')),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: T.s3),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _temperatureController,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      style: T.body,
                      decoration: InputDecoration(labelText: tr(context, 'temperature')),
                    ),
                  ),
                  const SizedBox(width: T.s3),
                  Expanded(
                    child: TextField(
                      controller: _weightController,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      style: T.body,
                      decoration: InputDecoration(labelText: tr(context, 'weightKg')),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: T.s3),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _sugarFastingController,
                      keyboardType: TextInputType.number,
                      style: T.body,
                      decoration: InputDecoration(
                        labelText: tr(context, 'sugarFasting'),
                        hintText: 'mg/dL',
                      ),
                    ),
                  ),
                  const SizedBox(width: T.s3),
                  Expanded(
                    child: TextField(
                      controller: _sugarRandomController,
                      keyboardType: TextInputType.number,
                      style: T.body,
                      decoration: InputDecoration(
                        labelText: tr(context, 'sugarRandom'),
                        hintText: 'mg/dL',
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: T.s3),
              TextField(
                controller: _pregnancyController,
                style: T.body,
                decoration: InputDecoration(labelText: tr(context, 'pregnancyStage')),
              ),
              const SizedBox(height: T.s3),
              DropdownButtonFormField<String>(
                value: _medicationCompliance,
                borderRadius: BorderRadius.circular(T.radius),
                decoration: InputDecoration(labelText: tr(context, 'medication')),
                items: _complianceLabels(context)
                    .entries
                    .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value, style: T.body)))
                    .toList(),
                onChanged: (v) => setState(() => _medicationCompliance = v ?? 'unknown'),
              ),
              if ((_extracted['violence_or_injury'] as List?)?.isNotEmpty ?? false) ...[
                const SizedBox(height: T.s4),
                Container(
                  padding: const EdgeInsets.all(T.s3),
                  decoration: BoxDecoration(
                    color: T.riskHigh.withValues(alpha: 0.07),
                    borderRadius: BorderRadius.circular(T.radius),
                    border: Border.all(color: T.riskHigh.withValues(alpha: 0.35)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        tr(context, 'safetyConcernHeard'),
                        style: T.strong.copyWith(color: T.riskHigh),
                      ),
                      const SizedBox(height: T.s1),
                      Text((_extracted['violence_or_injury'] as List).join(', '), style: T.body),
                      const SizedBox(height: T.s1),
                      Text(tr(context, 'safetyConcernNote'), style: T.caption),
                    ],
                  ),
                ),
              ],
              if ((_extracted['social_risk_factors'] as List?)?.isNotEmpty ?? false) ...[
                const SizedBox(height: T.s4),
                Text(tr(context, 'alsoNoted'), style: T.strong),
                const SizedBox(height: T.s1),
                Text((_extracted['social_risk_factors'] as List).join(', '), style: T.body),
              ],
            ],
          ),
        ),
        const SizedBox(height: T.s3),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _isSubmitting
                    ? null
                    : () => setState(() {
                          _isReviewingFields = false;
                          _isReviewing = true;
                        }),
                icon: const Icon(Icons.arrow_back),
                label: Text(tr(context, 'back')),
              ),
            ),
            const SizedBox(width: T.s3),
            Expanded(
              child: FilledButton.icon(
                onPressed: _isSubmitting ? null : _confirmAndSubmit,
                icon: _isSubmitting
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.check),
                label: Text(tr(context, _isSubmitting ? 'submitting' : 'confirmAndSubmit')),
              ),
            ),
          ],
        ),
      ];
}

/// Shows the pipeline output in the same order the demo script narrates
/// it: transcript -> risk -> generated actions.
class _ResultPanel extends StatelessWidget {
  final Map<String, dynamic> result;
  const _ResultPanel({required this.result});

  @override
  Widget build(BuildContext context) {
    final riskLevel = result['risk_level'] as String;
    final actions = (result['actions_generated'] as List).cast<Map<String, dynamic>>();
    final colour = T.risk(riskLevel);

    return Expanded(
      child: ListView(
        children: [
          Text(tr(context, 'transcript'), style: T.strong),
          const SizedBox(height: T.s1),
          Text(result['transcript'] as String, style: T.body),
          const SizedBox(height: T.s3),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: T.s3, vertical: T.s2),
            decoration: BoxDecoration(
              color: colour.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(T.radius),
              border: Border.all(color: colour.withValues(alpha: 0.35)),
            ),
            child: Text(
              '${tr(context, 'risk')}: $riskLevel',
              style: T.strong.copyWith(color: colour),
            ),
          ),
          const SizedBox(height: T.s3),
          Text(tr(context, 'generatedActions'), style: T.strong),
          const SizedBox(height: T.s1),
          for (final a in actions)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text('•  ${a['type']} — ${a['status']}', style: T.body),
            ),
        ],
      ),
    );
  }
}
