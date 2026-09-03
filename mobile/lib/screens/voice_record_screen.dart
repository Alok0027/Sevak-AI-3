import 'dart:convert';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../models/patient.dart';
import '../services/api_client.dart';
import '../services/offline_queue.dart';

/// FR-01.1/01.3/01.4: record a home-visit voice note, transcribe it and let
/// the ASHA review/correct the transcript before anything downstream runs
/// (risk scoring, referral drafting, HMIS reporting) -- a mishearing should
/// be a quick text edit here, never a silently-wrong risk classification.
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
  bool _isSubmitting = false;
  bool _isReviewing = false;
  String _languageCode = 'hi';
  String? _recordedPath;
  String? _pendingAudioBase64; // kept around for the offline-fallback path
  Map<String, dynamic>? _result;
  String? _statusMessage;

  static const _languages = {
    'hi': 'Hindi', 'mr': 'Marathi', 'ta': 'Tamil', 'te': 'Telugu', 'bn': 'Bengali',
  };

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.red.shade700),
    );
  }

  Future<void> _toggleRecording() async {
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
        _showError(
          'Microphone permission was denied. Enable it for this app in your phone\'s Settings, then try again.',
        );
        return;
      }
      final dir = await getTemporaryDirectory();
      final path = '${dir.path}/visit_${DateTime.now().millisecondsSinceEpoch}.m4a';
      await _recorder.start(const RecordConfig(), path: path);
      setState(() {
        _isRecording = true;
        _isReviewing = false;
        _result = null;
        _statusMessage = null;
      });
    } catch (e) {
      // Never let a mic failure look like an unresponsive button -- always
      // surface exactly what went wrong (permission plugin error, no mic
      // hardware, browser blocking access, etc).
      setState(() => _isRecording = false);
      _showError('Could not start recording: $e');
    }
  }

  /// Step 1: transcribe the recording and show it for review, instead of
  /// running it straight through the pipeline (FR-01.4).
  Future<void> _reviewTranscript() async {
    if (_recordedPath == null) return;
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
          languageCode: _languageCode,
        );
        setState(() => _statusMessage = 'Offline -- saved locally, will sync automatically when connected.');
        return;
      }

      final transcript = await widget.api.transcribeAudio(audioBase64: audioBase64, languageCode: _languageCode);
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
        languageCode: _languageCode,
      );
      setState(() => _statusMessage = 'Could not reach server -- saved locally, will retry sync. ($e)');
    } finally {
      if (mounted) setState(() => _isTranscribing = false);
    }
  }

  /// Step 2: submit exactly the (possibly hand-edited) text she reviewed --
  /// never a fresh re-transcription of the audio, which could differ from
  /// what she approved.
  Future<void> _confirmAndSubmit() async {
    final edited = _transcriptController.text.trim();
    if (edited.isEmpty) {
      _showError('Transcript is empty -- re-record, or type what happened by hand.');
      return;
    }
    setState(() {
      _isSubmitting = true;
      _statusMessage = null;
    });
    try {
      final result = await widget.api.submitVoiceVisit(
        workerId: widget.workerId,
        patientId: widget.patient.id,
        languageCode: _languageCode,
        confirmedTranscript: edited,
      );
      setState(() {
        _result = result;
        _isReviewing = false;
      });
    } catch (e) {
      // Network dropped between review and confirm -- fall back to queuing
      // the original audio so the visit isn't lost. Note this does mean
      // her edit doesn't carry through to the eventual sync (it'll be
      // freshly re-transcribed then); a rare edge case worth accepting
      // rather than losing the visit entirely.
      if (_pendingAudioBase64 != null) {
        await _queue.enqueueVisit(
          workerId: widget.workerId,
          patientId: widget.patient.id,
          audioBase64: _pendingAudioBase64!,
          languageCode: _languageCode,
        );
        setState(() {
          _statusMessage = 'Could not reach server -- saved locally, will retry sync. ($e)';
          _isReviewing = false;
        });
      } else {
        _showError('Could not submit: $e');
      }
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  void _reRecord() {
    setState(() {
      _isReviewing = false;
      _recordedPath = null;
      _pendingAudioBase64 = null;
      _transcriptController.clear();
    });
  }

  @override
  void dispose() {
    _recorder.dispose();
    _transcriptController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.patient.name)),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (!_isReviewing) ...[
              DropdownButtonFormField<String>(
                value: _languageCode,
                decoration: const InputDecoration(labelText: 'Language', border: OutlineInputBorder()),
                items: _languages.entries
                    .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value)))
                    .toList(),
                onChanged: (v) => setState(() => _languageCode = v ?? 'hi'),
              ),
              const SizedBox(height: 24),
              Center(
                child: GestureDetector(
                  onTap: _toggleRecording,
                  child: CircleAvatar(
                    radius: 48,
                    backgroundColor: _isRecording ? Colors.red : Theme.of(context).colorScheme.primary,
                    child: Icon(_isRecording ? Icons.stop : Icons.mic, size: 48, color: Colors.white),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Center(child: Text(_isRecording ? 'Recording... tap to stop' : 'Tap to record observation')),
              const SizedBox(height: 20),
              if (_recordedPath != null && !_isRecording)
                FilledButton.icon(
                  onPressed: _isTranscribing ? null : _reviewTranscript,
                  icon: _isTranscribing
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.hearing),
                  label: Text(_isTranscribing ? 'Transcribing...' : 'Review what was heard'),
                ),
            ] else ...[
              Text('Is this what you said?', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(
                'Fix anything that was heard wrong before it\'s processed.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 12),
              Expanded(
                child: TextField(
                  controller: _transcriptController,
                  maxLines: null,
                  expands: true,
                  textAlignVertical: TextAlignVertical.top,
                  decoration: const InputDecoration(border: OutlineInputBorder(), contentPadding: EdgeInsets.all(12)),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _isSubmitting ? null : _reRecord,
                      icon: const Icon(Icons.mic),
                      label: const Text('Re-record'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: _isSubmitting ? null : _confirmAndSubmit,
                      icon: _isSubmitting
                          ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.check),
                      label: Text(_isSubmitting ? 'Submitting...' : 'Confirm & submit'),
                    ),
                  ),
                ],
              ),
            ],
            if (_statusMessage != null) Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(_statusMessage!, style: const TextStyle(color: Colors.orange)),
            ),
            if (_result != null) ...[
              const Divider(height: 32),
              _ResultPanel(result: _result!),
            ],
          ],
        ),
      ),
    );
  }
}

/// Shows the pipeline output the same order the demo script narrates it:
/// transcript -> structured record -> risk -> generated actions.
class _ResultPanel extends StatelessWidget {
  final Map<String, dynamic> result;
  const _ResultPanel({required this.result});

  @override
  Widget build(BuildContext context) {
    final riskLevel = result['risk_level'] as String;
    final actions = (result['actions_generated'] as List).cast<Map<String, dynamic>>();
    final riskColor = switch (riskLevel) {
      'HIGH' => Colors.red,
      'MEDIUM' => Colors.amber.shade700,
      _ => Colors.green,
    };

    return Expanded(
      child: ListView(
        children: [
          Text('Transcript', style: Theme.of(context).textTheme.titleSmall),
          Text(result['transcript'] as String),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: riskColor.withOpacity(0.15), borderRadius: BorderRadius.circular(8)),
            child: Text('RISK: $riskLevel', style: TextStyle(color: riskColor, fontWeight: FontWeight.bold)),
          ),
          const SizedBox(height: 12),
          Text('Generated actions', style: Theme.of(context).textTheme.titleSmall),
          for (final a in actions)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Text('• [${a['type']}] ${a['status']}'),
            ),
        ],
      ),
    );
  }
}
