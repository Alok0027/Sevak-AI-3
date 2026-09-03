import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../models/patient.dart';
import '../services/api_client.dart';

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

  const AddPatientScreen({super.key, required this.api});

  @override
  State<AddPatientScreen> createState() => _AddPatientScreenState();
}

class _AddPatientScreenState extends State<AddPatientScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _ageController = TextEditingController();
  final _villageController = TextEditingController();
  final _phoneController = TextEditingController();
  final _pregnancyController = TextEditingController();
  final _genderController = TextEditingController();
  bool _saving = false;
  String? _error;

  final _recorder = AudioRecorder();
  bool _isRecording = false;
  bool _isProcessingVoice = false;
  String? _lastTranscript;
  String _languageCode = 'hi';

  static const _languages = {
    'hi': 'Hindi', 'mr': 'Marathi', 'ta': 'Tamil', 'te': 'Telugu', 'bn': 'Bengali',
  };

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.red.shade700),
    );
  }

  Future<void> _toggleVoiceIntake() async {
    try {
      if (_isRecording) {
        final path = await _recorder.stop();
        setState(() => _isRecording = false);
        if (path != null) await _processRecording(path);
        return;
      }
      final hasPermission = await _recorder.hasPermission();
      if (!hasPermission) {
        _showError(
          'Microphone permission was denied. Enable it for this app in your phone\'s Settings, then try again.',
        );
        return;
      }
      final dir = await getTemporaryDirectory();
      final path = '${dir.path}/patient_intake_${DateTime.now().millisecondsSinceEpoch}.m4a';
      await _recorder.start(const RecordConfig(), path: path);
      setState(() {
        _isRecording = true;
        _lastTranscript = null;
      });
    } catch (e) {
      setState(() => _isRecording = false);
      _showError('Could not start recording: $e');
    }
  }

  Future<void> _processRecording(String path) async {
    setState(() => _isProcessingVoice = true);
    try {
      final bytes = await File(path).readAsBytes();
      final audioBase64 = base64Encode(bytes);
      final result = await widget.api.voiceIntake(audioBase64: audioBase64, languageCode: _languageCode);
      final extracted = result['extracted'] as Map<String, dynamic>;
      setState(() {
        _lastTranscript = result['transcript'] as String?;
        if (extracted['name'] != null) _nameController.text = extracted['name'] as String;
        if (extracted['age'] != null) _ageController.text = '${extracted['age']}';
        if (extracted['gender'] != null) _genderController.text = extracted['gender'] as String;
        if (extracted['village'] != null) _villageController.text = extracted['village'] as String;
        if (extracted['phone'] != null) _phoneController.text = extracted['phone'] as String;
      });
      final gotNothing = extracted['name'] == null &&
          extracted['age'] == null &&
          extracted['gender'] == null &&
          extracted['village'] == null &&
          extracted['phone'] == null;
      if (gotNothing) {
        _showError('Didn\'t catch any details in that -- try again, or fill the form in by hand.');
      }
    } catch (e) {
      _showError('Could not process the recording: $e');
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
      final patient = await widget.api.createPatient(
        name: _nameController.text.trim(),
        age: age.isEmpty ? null : int.tryParse(age),
        gender: gender.isEmpty ? null : gender,
        village: village.isEmpty ? null : village,
        phone: phone.isEmpty ? null : phone,
        pregnancyStage: pregnancy.isEmpty ? null : pregnancy,
      );
      if (!mounted) return;
      Navigator.of(context).pop(patient);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  void dispose() {
    _nameController.dispose();
    _ageController.dispose();
    _villageController.dispose();
    _phoneController.dispose();
    _pregnancyController.dispose();
    _genderController.dispose();
    _recorder.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Add patient')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Card(
              margin: EdgeInsets.zero,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    Text(
                      'Speak the patient\'s details instead of typing',
                      style: Theme.of(context).textTheme.titleSmall,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'e.g. "Sunita Devi, 32 saal, gaon Wagholi, phone 9876543210, female"',
                      style: Theme.of(context).textTheme.bodySmall,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      value: _languageCode,
                      decoration: const InputDecoration(labelText: 'Language', border: OutlineInputBorder(), isDense: true),
                      items: _languages.entries
                          .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value)))
                          .toList(),
                      onChanged: (v) => setState(() => _languageCode = v ?? 'hi'),
                    ),
                    const SizedBox(height: 12),
                    GestureDetector(
                      onTap: _isProcessingVoice ? null : _toggleVoiceIntake,
                      child: CircleAvatar(
                        radius: 32,
                        backgroundColor: _isRecording ? Colors.red : Theme.of(context).colorScheme.primary,
                        child: _isProcessingVoice
                            ? const SizedBox(
                                width: 22, height: 22,
                                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                            : Icon(_isRecording ? Icons.stop : Icons.mic, size: 32, color: Colors.white),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _isProcessingVoice
                          ? 'Listening back...'
                          : (_isRecording ? 'Recording -- tap to stop' : 'Tap to speak'),
                    ),
                    if (_lastTranscript != null) ...[
                      const SizedBox(height: 10),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: Theme.of(context).colorScheme.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text('Heard: "$_lastTranscript"', style: Theme.of(context).textTheme.bodySmall),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Check the fields below and fix anything it got wrong before saving.',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(fontStyle: FontStyle.italic),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),
            TextFormField(
              controller: _nameController,
              decoration: const InputDecoration(labelText: 'Full name *', border: OutlineInputBorder()),
              textCapitalization: TextCapitalization.words,
              validator: (v) => (v == null || v.trim().isEmpty) ? 'Name is required' : null,
            ),
            const SizedBox(height: 12),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _ageController,
                    decoration: const InputDecoration(labelText: 'Age', border: OutlineInputBorder()),
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextFormField(
                    controller: _genderController,
                    decoration: const InputDecoration(labelText: 'Gender', border: OutlineInputBorder()),
                    textCapitalization: TextCapitalization.words,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _villageController,
              decoration: const InputDecoration(labelText: 'Village', border: OutlineInputBorder()),
              textCapitalization: TextCapitalization.words,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _pregnancyController,
              decoration: const InputDecoration(
                labelText: 'Pregnancy stage (if applicable)',
                hintText: 'e.g. 5 months',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _phoneController,
              decoration: const InputDecoration(labelText: 'Phone (optional)', border: OutlineInputBorder()),
              keyboardType: TextInputType.phone,
            ),
            const SizedBox(height: 20),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(_error!, style: const TextStyle(color: Colors.red)),
              ),
            FilledButton.icon(
              onPressed: _saving ? null : _save,
              icon: _saving
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Icon(Icons.check),
              label: const Text('Save patient'),
            ),
          ],
        ),
      ),
    );
  }
}
