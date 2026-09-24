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
import '../widgets/status_group.dart';

/// Lets an ASHA worker register a new patient before her first visit with
/// them -- POST /api/v1/patients, scoped server-side to the signed-in
/// worker. Only name is required; everything else can be filled in now or
/// corrected later from a visit.
///
/// FR-07.2 voice-fill: she can also tap the mic and just say the patient's
/// details ("Sunita Devi, 32 saal, gaon Wagholi, phone 9876543210, female")
/// instead of typing them one field at a time. The backend transcribes and
/// extracts what it can hear into the same fields below -- still shown as
/// an editable form, never saved directly, so she always reviews/corrects
/// before tapping Save (same review-before-trust principle as the visit
/// recording screen).
class AddPatientScreen extends StatefulWidget {
  final ApiClient api;

  final String workerId;

  const AddPatientScreen({super.key, required this.api, required this.workerId});

  @override
  State<AddPatientScreen> createState() => _AddPatientScreenState();
}

class _AddPatientScreenState extends State<AddPatientScreen> {
  final _queue = OfflineQueue();

  /// Audio recorded with no signal, waiting to travel with the record.
  ///
  /// Speech recognition runs on the server, so the phone cannot turn this
  /// into fields at the doorstep. Throwing it away would make the
  /// microphone useless offline -- the opposite of what this app is for --
  /// so it is kept and queued with the patient, and the server fills in
  /// whatever she did not type when the sync runs.
  String? _pendingAudioBase64;
  String? _pendingAudioLanguage;
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _ageController = TextEditingController();
  final _villageController = TextEditingController();
  final _phoneController = TextEditingController();
  final _pregnancyController = TextEditingController();
  final _genderController = TextEditingController();
  // The number on her MCP card -- the identifier the sub-centre's RCH
  // register, the ANM's line-list and every referral form already use.
  // Optional, because an ASHA meeting a woman at her door before the
  // sub-centre has registered her has none to type, and refusing the
  // record until she does pushes the work back onto paper.
  final _rchController = TextEditingController();
  // Baseline vitals taken at registration. Fasting and random blood sugar
  // are separate fields because the NHM cutoffs differ (>=126 vs >=200
  // mg/dL) -- one box can't be judged against either.
  final _bpSystolicController = TextEditingController();
  final _bpDiastolicController = TextEditingController();
  final _sugarFastingController = TextEditingController();
  final _sugarRandomController = TextEditingController();
  bool _saving = false;
  String? _error;

  final _recorder = AudioRecorder();
  bool _isRecording = false;
  bool _isProcessingVoice = false;
  String? _lastTranscript;
  String? _speechLanguage; // null = follow the app's UI language

  /// The language she'll *speak* in, which is not necessarily the one the
  /// app is showing -- an ASHA may read the interface in Hindi and take a
  /// history in Marathi. Defaults to the UI language because that's right
  /// most of the time, and stays changeable because sometimes it isn't.
  /// Each option is written in its own script for the same reason the
  /// app-bar picker is.
  static const _speechLanguages = {
    'hi': 'हिन्दी',
    'mr': 'मराठी',
    'ta': 'தமிழ்',
    'te': 'తెలుగు',
    'bn': 'বাংলা',
  };

  String _effectiveSpeechLanguage(BuildContext context) {
    if (_speechLanguage != null) return _speechLanguage!;
    final ui = Localizations.localeOf(context).languageCode;
    return _speechLanguages.containsKey(ui) ? ui : 'hi';
  }

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: T.riskHigh),
    );
  }

  Future<void> _toggleVoiceIntake() async {
    // Everything that reads `context` is read before the first await --
    // past that point this widget may already be gone, and looking up
    // Localizations on a dead context throws.
    final language = _effectiveSpeechLanguage(context);
    final micMessage = tr(context, 'micDenied');
    final startFailed = tr(context, 'couldNotStartRecording');
    final processFailed = tr(context, 'couldNotProcessRecording');
    final heardNothing = tr(context, 'heardNothing');
    try {
      if (_isRecording) {
        final path = await _recorder.stop();
        // Guarded from here down: she can back out of this screen while a
        // recording is stopping or an intake request is in flight, and a
        // setState on a disposed State throws.
        if (!mounted) return;
        setState(() => _isRecording = false);
        if (path != null) {
          await _processRecording(path, language, processFailed, heardNothing);
        }
        return;
      }
      final hasPermission = await _recorder.hasPermission();
      if (!hasPermission) {
        _showError(micMessage);
        return;
      }
      final dir = await getTemporaryDirectory();
      final path = '${dir.path}/patient_intake_${DateTime.now().millisecondsSinceEpoch}.m4a';
      await _recorder.start(const RecordConfig(), path: path);
      if (!mounted) return;
      setState(() {
        _isRecording = true;
        _lastTranscript = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _isRecording = false);
      _showError('$startFailed: ${readableError(e)}');
    }
  }

  Future<void> _processRecording(
    String path,
    String languageCode,
    String processFailed,
    String heardNothing,
  ) async {
    final needsInternet = tr(context, 'voiceNeedsInternet');
    setState(() => _isProcessingVoice = true);
    try {
      // Speech recognition happens on the server, so this one button
      // genuinely cannot work without a signal -- unlike recording a
      // visit, which queues the audio and transcribes it on sync.
      //
      // Checked before the call rather than caught after it, because the
      // failure otherwise arrives as "Failed host lookup ... errno = 7"
      // in a red banner, which tells an ASHA nothing about what to do
      // next. What she needs to know is: type it instead.
      final connectivity = await Connectivity().checkConnectivity();
      final bytes = await File(path).readAsBytes();
      final audioBase64 = base64Encode(bytes);

      if (connectivity.contains(ConnectivityResult.none)) {
        // Hold it rather than refuse it. She still types the name -- the
        // one field the server cannot invent -- and everything else she
        // spoke is filled in when the queue flushes.
        if (mounted) {
          setState(() {
            _pendingAudioBase64 = audioBase64;
            _pendingAudioLanguage = languageCode;
            _isProcessingVoice = false;
          });
          ScaffoldMessenger.of(context)
              .showSnackBar(SnackBar(content: Text(needsInternet)));
        }
        return;
      }

      final result = await widget.api.voiceIntake(audioBase64: audioBase64, languageCode: languageCode);
      final extracted = result['extracted'] as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _lastTranscript = result['transcript'] as String?;
        if (extracted['name'] != null) _nameController.text = extracted['name'] as String;
        if (extracted['age'] != null) _ageController.text = '${extracted['age']}';
        if (extracted['gender'] != null) _genderController.text = extracted['gender'] as String;
        if (extracted['village'] != null) _villageController.text = extracted['village'] as String;
        if (extracted['phone'] != null) _phoneController.text = extracted['phone'] as String;
        if (extracted['pregnancy_stage'] != null) {
          _pregnancyController.text = extracted['pregnancy_stage'] as String;
        }
        if (extracted['bp_systolic'] != null) _bpSystolicController.text = '${extracted['bp_systolic']}';
        if (extracted['bp_diastolic'] != null) _bpDiastolicController.text = '${extracted['bp_diastolic']}';
        if (extracted['blood_sugar_fasting'] != null) {
          _sugarFastingController.text = '${extracted['blood_sugar_fasting']}';
        }
        if (extracted['blood_sugar_random'] != null) {
          _sugarRandomController.text = '${extracted['blood_sugar_random']}';
        }
      });
      final gotNothing = extracted.values.every((v) => v == null || v is Map && v.isEmpty);
      if (gotNothing) _showError(heardNothing);
    } catch (e) {
      if (mounted) _showError('$processFailed: ${readableError(e)}');
    } finally {
      if (mounted) setState(() => _isProcessingVoice = false);
    }
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final age = _ageController.text.trim();
      final village = _villageController.text.trim();
      final phone = _phoneController.text.trim();
      final pregnancy = _pregnancyController.text.trim();
      final gender = _genderController.text.trim();
      final rch = _rchController.text.trim();
      // Registering a patient is on the offline path (FR-07.1), same as
      // recording a visit: an ASHA standing in a house with no signal has
      // to be able to save the woman in front of her and move on. The id
      // is minted here so the visit she may record two minutes later can
      // reference it before the server has ever heard of her.
      final connectivity = await Connectivity().checkConnectivity();
      if (connectivity.contains(ConnectivityResult.none)) {
        final local = await _queueLocally();
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(tr(context, 'offlineSaved'))),
        );
        Navigator.of(context).pop(local);
        return;
      }

      final patient = await widget.api.createPatient(
        name: _nameController.text.trim(),
        age: age.isEmpty ? null : int.tryParse(age),
        gender: gender.isEmpty ? null : gender,
        village: village.isEmpty ? null : village,
        phone: phone.isEmpty ? null : phone,
        pregnancyStage: pregnancy.isEmpty ? null : pregnancy,
        rchNumber: rch.isEmpty ? null : rch,
        bpSystolic: int.tryParse(_bpSystolicController.text.trim()),
        bpDiastolic: int.tryParse(_bpDiastolicController.text.trim()),
        bloodSugarFasting: int.tryParse(_sugarFastingController.text.trim()),
        bloodSugarRandom: int.tryParse(_sugarRandomController.text.trim()),
      );
      if (!mounted) return;
      Navigator.of(context).pop(patient);
    } catch (e) {
      // Two very different failures arrive here and used to be treated the
      // same way.
      //
      // The server understood and refused -- she is already on somebody's
      // list, or the RCH number is not twelve digits. Queueing that hides
      // a decision the ASHA could act on at the doorstep behind a flush
      // that fails again tomorrow with nobody watching. Tell her.
      //
      // The server could not be reached at all. Queue it, because the
      // ASHA has already done the work of asking and a real woman's
      // details are worth more than a tidy queue.
      final status = e is ApiException ? e.status : null;
      if (status != null && status >= 400 && status < 500) {
        if (!mounted) return;
        setState(() {
          _error = status == 409
              ? tr(context, 'alreadyRegistered')
              : (e as ApiException).message;
        });
        return;
      }
      try {
        final local = await _queueLocally();
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(tr(context, 'offlineSaved'))),
        );
        Navigator.of(context).pop(local);
        return;
      } catch (_) {
        if (mounted) setState(() => _error = readableError(e));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// Write the form to the offline queue and hand back the patient the
  /// list should show in the meantime, carrying the id sync will use.
  Future<Patient> _queueLocally() async {
    final id = OfflineQueue.newLocalId();
    final age = _ageController.text.trim();
    final village = _villageController.text.trim();
    final phone = _phoneController.text.trim();
    final pregnancy = _pregnancyController.text.trim();
    final gender = _genderController.text.trim();
    final name = _nameController.text.trim();
    final rch = _rchController.text.trim();
    await _queue.enqueuePatient(
      workerId: widget.workerId,
      patientId: id,
      name: name,
      age: age.isEmpty ? null : int.tryParse(age),
      gender: gender.isEmpty ? null : gender,
      village: village.isEmpty ? null : village,
      phone: phone.isEmpty ? null : phone,
      pregnancyStage: pregnancy.isEmpty ? null : pregnancy,
      rchNumber: rch.isEmpty ? null : rch,
      audioBase64: _pendingAudioBase64,
      languageCode: _pendingAudioLanguage,
    );
    return Patient(
      id: id,
      name: name,
      age: age.isEmpty ? null : int.tryParse(age),
      village: village.isEmpty ? null : village,
      pregnancyStage: pregnancy.isEmpty ? null : pregnancy,
    );
  }

  @override
  void dispose() {
    _nameController.dispose();
    _ageController.dispose();
    _villageController.dispose();
    _phoneController.dispose();
    _pregnancyController.dispose();
    _genderController.dispose();
    _rchController.dispose();
    _bpSystolicController.dispose();
    _bpDiastolicController.dispose();
    _sugarFastingController.dispose();
    _sugarRandomController.dispose();
    _recorder.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr(context, 'addPatient'))),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(T.s4, T.s4, T.s4, T.s8),
          children: [
            _VoicePanel(
              languages: _speechLanguages,
              selected: _effectiveSpeechLanguage(context),
              onLanguageChanged: (v) => setState(() => _speechLanguage = v),
              isRecording: _isRecording,
              isProcessing: _isProcessingVoice,
              transcript: _lastTranscript,
              onTap: _isProcessingVoice ? null : _toggleVoiceIntake,
            ),
            const SizedBox(height: T.s6),
            TextFormField(
              controller: _nameController,
              style: T.body,
              decoration: InputDecoration(labelText: '${tr(context, 'fullName')} *'),
              textCapitalization: TextCapitalization.words,
              validator: (v) => (v == null || v.trim().isEmpty) ? tr(context, 'nameRequired') : null,
            ),
            const SizedBox(height: T.s3),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _ageController,
                    style: T.body,
                    decoration: InputDecoration(labelText: tr(context, 'age')),
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: T.s3),
                Expanded(
                  child: TextFormField(
                    controller: _genderController,
                    style: T.body,
                    decoration: InputDecoration(labelText: tr(context, 'gender')),
                    textCapitalization: TextCapitalization.words,
                  ),
                ),
              ],
            ),
            const SizedBox(height: T.s3),
            TextFormField(
              controller: _villageController,
              style: T.body,
              decoration: InputDecoration(labelText: tr(context, 'village')),
              textCapitalization: TextCapitalization.words,
            ),
            const SizedBox(height: T.s3),
            TextFormField(
              controller: _pregnancyController,
              style: T.body,
              decoration: InputDecoration(labelText: tr(context, 'pregnancyStage')),
            ),
            const SizedBox(height: T.s3),
            TextFormField(
              controller: _phoneController,
              style: T.body,
              decoration: InputDecoration(labelText: tr(context, 'phoneOptional')),
              keyboardType: TextInputType.phone,
            ),
            const SizedBox(height: T.s3),
            TextFormField(
              controller: _rchController,
              style: T.body,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                labelText: tr(context, 'rchNumber'),
                helperText: tr(context, 'rchHint'),
                helperMaxLines: 3,
              ),
              // Checked here as well as on the server, because the server's
              // refusal arrives after she has filled in the whole form and
              // the card is in her hand right now.
              validator: (v) {
                final digits = (v ?? '').replaceAll(RegExp(r'\D'), '');
                if (digits.isEmpty) return null;
                return digits.length == 12 ? null : tr(context, 'rchHint');
              },
            ),
            const SizedBox(height: T.s6),
            SectionHeading(tr(context, 'baselineReadings')),
            Text(tr(context, 'baselineNote'), style: T.caption),
            const SizedBox(height: T.s3),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _bpSystolicController,
                    style: T.body,
                    decoration: InputDecoration(labelText: tr(context, 'bpUpper')),
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: T.s3),
                Expanded(
                  child: TextFormField(
                    controller: _bpDiastolicController,
                    style: T.body,
                    decoration: InputDecoration(labelText: tr(context, 'bpLower')),
                    keyboardType: TextInputType.number,
                  ),
                ),
              ],
            ),
            const SizedBox(height: T.s3),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _sugarFastingController,
                    style: T.body,
                    decoration: InputDecoration(
                      labelText: tr(context, 'sugarFasting'),
                      hintText: 'mg/dL',
                    ),
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: T.s3),
                Expanded(
                  child: TextFormField(
                    controller: _sugarRandomController,
                    style: T.body,
                    decoration: InputDecoration(
                      labelText: tr(context, 'sugarRandom'),
                      hintText: 'mg/dL',
                    ),
                    keyboardType: TextInputType.number,
                  ),
                ),
              ],
            ),
            const SizedBox(height: T.s6),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: T.s3),
                child: Text(_error!, style: T.caption.copyWith(color: T.riskHigh)),
              ),
            FilledButton.icon(
              onPressed: _saving ? null : _save,
              icon: _saving
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Icon(Icons.check),
              label: Text(tr(context, 'savePatient')),
            ),
          ],
        ),
      ),
    );
  }
}

/// The voice-fill panel: one big target, the language she'll speak in,
/// and — once it's heard something — the transcript it worked from, so a
/// wrong field has a visible cause.
class _VoicePanel extends StatelessWidget {
  final Map<String, String> languages;
  final String selected;
  final ValueChanged<String> onLanguageChanged;
  final bool isRecording;
  final bool isProcessing;
  final String? transcript;
  final VoidCallback? onTap;

  const _VoicePanel({
    required this.languages,
    required this.selected,
    required this.onLanguageChanged,
    required this.isRecording,
    required this.isProcessing,
    required this.transcript,
    required this.onTap,
  });

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
        children: [
          Text(tr(context, 'speakDetails'), style: T.section, textAlign: TextAlign.center),
          const SizedBox(height: T.s1),
          Text(tr(context, 'speakExample'), style: T.caption, textAlign: TextAlign.center),
          const SizedBox(height: T.s4),
          DropdownButtonFormField<String>(
            initialValue: selected,
            isDense: true,
            borderRadius: BorderRadius.circular(T.radius),
            decoration: InputDecoration(labelText: tr(context, 'language'), isDense: true),
            items: languages.entries
                .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value, style: T.body)))
                .toList(),
            onChanged: (v) {
              if (v != null) onLanguageChanged(v);
            },
          ),
          const SizedBox(height: T.s4),
          // 72dp: the one control on this screen she uses without looking.
          Semantics(
            button: true,
            label: tr(context, isRecording ? 'recordingTapStop' : 'tapToSpeak'),
            child: InkWell(
              onTap: onTap,
              customBorder: const CircleBorder(),
              child: Container(
                width: 72,
                height: 72,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: isRecording ? T.riskHigh : T.forest,
                  shape: BoxShape.circle,
                ),
                child: isProcessing
                    ? const SizedBox(
                        width: 24,
                        height: 24,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : Icon(isRecording ? Icons.stop : Icons.mic, size: 32, color: Colors.white),
              ),
            ),
          ),
          const SizedBox(height: T.s2),
          Text(
            isProcessing
                ? tr(context, 'listeningBack')
                : tr(context, isRecording ? 'recordingTapStop' : 'tapToSpeak'),
            style: T.caption,
          ),
          if (transcript != null) ...[
            const SizedBox(height: T.s3),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(T.s3),
              decoration: BoxDecoration(
                color: T.sage,
                borderRadius: BorderRadius.circular(T.radius),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(tr(context, 'heard'), style: T.micro.copyWith(color: T.forest)),
                  const SizedBox(height: 2),
                  // The transcript is in the language she spoke -- shown
                  // exactly as heard, never translated.
                  Text('“$transcript”', style: T.body),
                ],
              ),
            ),
            const SizedBox(height: T.s2),
            Text(tr(context, 'checkFieldsBelow'), style: T.caption),
          ],
        ],
      ),
    );
  }
}
