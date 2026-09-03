import 'dart:convert';
import 'package:http/http.dart' as http;

import '../models/history_models.dart';
import '../models/patient.dart';

/// Talks to the FastAPI backend (../backend). Point [baseUrl] at your dev
/// machine's LAN IP when testing on a physical device -- "localhost" only
/// works from an emulator on the same host.
class ApiClient {
  final String baseUrl;
  String? _token;

  ApiClient({this.baseUrl = 'http://192.168.4.105:8000'});

  void setToken(String token) => _token = token;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_token != null) 'Authorization': 'Bearer $_token',
      };

  Future<Map<String, dynamic>> login(String phone, String pin) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'phone': phone, 'pin': pin}),
    );
    if (resp.statusCode != 200) {
      throw ApiException('Login failed: ${resp.body}');
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    _token = data['access_token'] as String;
    return data;
  }

  /// Register a new patient under the signed-in ASHA worker -- must happen
  /// before her first visit with them (FR-07.2 prerequisite). Only [name]
  /// is required; everything else can be added or corrected later.
  Future<Patient> createPatient({
    required String name,
    int? age,
    String? gender,
    String? village,
    String? phone,
    String? pregnancyStage,
  }) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/patients'),
      headers: _headers,
      body: jsonEncode({
        'name': name,
        'age': age,
        'gender': gender,
        'village': village,
        'phone': phone,
        'pregnancy_stage': pregnancyStage,
      }),
    );
    if (resp.statusCode != 201) {
      throw ApiException('Failed to add patient: ${resp.body}');
    }
    return Patient.fromJson(jsonDecode(resp.body) as Map<String, dynamic>);
  }

  /// FR-07.2 voice-fill: transcribe a spoken patient description and get
  /// back suggested name/age/gender/village/phone to pre-fill the Add
  /// Patient form with. Read-only on the backend -- nothing is saved until
  /// the ASHA reviews the pre-filled form and taps Save herself.
  Future<Map<String, dynamic>> voiceIntake({
    required String audioBase64,
    required String languageCode,
  }) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/patients/voice-intake'),
      headers: _headers,
      body: jsonEncode({'audio_base64': audioBase64, 'language_code': languageCode}),
    );
    if (resp.statusCode != 200) {
      throw ApiException('Voice intake failed: ${resp.body}');
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  Future<List<Patient>> fetchPatients(String workerId) async {
    final resp = await http.get(Uri.parse('$baseUrl/api/v1/patients/$workerId'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException('Failed to load patients: ${resp.body}');
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    return (data['patients'] as List).map((p) => Patient.fromJson(p as Map<String, dynamic>)).toList();
  }

  /// FR-01.4: transcribe a recording without running the rest of the
  /// pipeline, so it can be shown to the ASHA for review/correction before
  /// anything downstream (risk scoring, referral drafting) happens.
  Future<String> transcribeAudio({required String audioBase64, required String languageCode}) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/visits/transcribe'),
      headers: _headers,
      body: jsonEncode({'audio_base64': audioBase64, 'language_code': languageCode}),
    );
    if (resp.statusCode != 200) {
      throw ApiException('Transcription failed: ${resp.body}');
    }
    return (jsonDecode(resp.body) as Map<String, dynamic>)['transcript'] as String;
  }

  /// FR-01.1/01.2: run the full 5-agent pipeline. Pass either [audioBase64]
  /// (it gets transcribed server-side) or [confirmedTranscript] -- the text
  /// the ASHA already reviewed via [transcribeAudio] -- in which case that
  /// exact text is used verbatim, never re-transcribed.
  /// Throws on any network failure -- callers should fall back to queuing
  /// the record offline (see OfflineQueue) rather than losing the visit.
  Future<Map<String, dynamic>> submitVoiceVisit({
    required String workerId,
    required String patientId,
    required String languageCode,
    String? audioBase64,
    String? confirmedTranscript,
  }) async {
    assert(audioBase64 != null || confirmedTranscript != null);
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/visits/voice'),
      headers: _headers,
      body: jsonEncode({
        'worker_id': workerId,
        'patient_id': patientId,
        'language_code': languageCode,
        if (audioBase64 != null) 'audio_base64': audioBase64,
        if (confirmedTranscript != null) 'confirmed_transcript': confirmedTranscript,
      }),
    );
    if (resp.statusCode != 200) {
      throw ApiException('Voice visit failed: ${resp.body}');
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  /// FR-07.3: pending follow-up tasks, sorted by urgency by the backend.
  Future<List<Map<String, dynamic>>> fetchTasks(String workerId) async {
    final resp = await http.get(Uri.parse('$baseUrl/api/v1/tasks/$workerId'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException('Failed to load tasks: ${resp.body}');
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    return (data['tasks'] as List).cast<Map<String, dynamic>>();
  }

  /// Marks a follow-up task done from the app -- this is what lets the
  /// ANM/BMO "done vs pending" chart reflect real completions from the
  /// field rather than a count that only ever grows.
  Future<void> completeTask(String actionId) async {
    final resp = await http.post(Uri.parse('$baseUrl/api/v1/tasks/$actionId/complete'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException('Failed to complete task: ${resp.body}');
    }
  }

  /// The signed-in worker's own real stats (patients treated, visits,
  /// HIGH-risk flags, pending follow-ups) plus her full visit timeline --
  /// backs the ASHA home screen. Also used by ANM/BMO roster drill-downs.
  Future<WorkerHistory> fetchWorkerHistory(String workerId) async {
    final resp = await http.get(Uri.parse('$baseUrl/api/v1/workers/$workerId/history'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException('Failed to load worker history: ${resp.body}');
    }
    return WorkerHistory.fromJson(jsonDecode(resp.body) as Map<String, dynamic>);
  }

  /// A patient's full visit timeline (transcript + extracted structured
  /// record per visit) -- backs the patient detail screen.
  Future<PatientHistory> fetchPatientHistory(String patientId) async {
    final resp = await http.get(Uri.parse('$baseUrl/api/v1/patients/$patientId/history'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException('Failed to load patient history: ${resp.body}');
    }
    return PatientHistory.fromJson(jsonDecode(resp.body) as Map<String, dynamic>);
  }

  /// FR-01.3/FR-07.1: flush the offline queue once connectivity returns.
  Future<Map<String, dynamic>> syncBatch(String workerId, List<Map<String, dynamic>> records) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/sync/batch'),
      headers: _headers,
      body: jsonEncode({'worker_id': workerId, 'records': records}),
    );
    if (resp.statusCode != 200) {
      throw ApiException('Sync failed: ${resp.body}');
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }
}

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}
