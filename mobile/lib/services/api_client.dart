import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;

import '../models/history_models.dart';
import '../models/patient.dart';
import 'patient_cache.dart';

/// Talks to the FastAPI backend (../backend).
///
/// The default is the deployed backend, so an APK handed to someone --
/// a reviewer, a teammate, a judge -- works on their phone over mobile
/// data with no arguments and no build flags. It used to default to a
/// laptop's LAN address, which meant every installed APK pointed at a
/// machine that was not on the network and failed at login with a
/// connection error.
///
/// Local development overrides it at launch, so nobody has to edit this
/// file when DHCP reassigns their IP:
///
///     flutter run --dart-define=SEVAKAI_API=http://192.168.1.42:8000
///
///   - physical device on the same wifi: the dev machine's LAN IP, above
///   - Android emulator: http://10.0.2.2:8000 (the host, seen from inside)
///   - iOS simulator: http://localhost:8000
///
/// Plain http works in debug builds only -- android/app/src/debug/
/// AndroidManifest.xml permits cleartext there and nowhere else, so a
/// release build must point at an https URL.
class ApiClient {
  final String baseUrl;
  String? _token;

  static const _defaultBaseUrl = String.fromEnvironment(
    'SEVAKAI_API',
    defaultValue: 'https://sevakai-api.onrender.com',
  );

  ApiClient({String? baseUrl}) : baseUrl = baseUrl ?? _defaultBaseUrl;

  void setToken(String token) => _token = token;
  void clearToken() => _token = null;

  Future<List<dynamic>> notificationInbox() async {
    final response = await http.get(Uri.parse('$baseUrl/api/v1/notifications'), headers: _headers);
    if (response.statusCode != 200) throw ApiException('Could not load notifications');
    return jsonDecode(response.body)['notifications'] as List<dynamic>;
  }

  Future<Map<String, dynamic>> notificationPreview(String id, String channel) async {
    final response = await http.get(Uri.parse('$baseUrl/api/v1/notifications/$id/preview?channel=$channel'), headers: _headers);
    if (response.statusCode != 200) throw ApiException(response.body);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<void> approveNotification(String id, String channel, String previewHash) async {
    final response = await http.post(Uri.parse('$baseUrl/api/v1/notifications/$id/approve'), headers: _headers,
        body: jsonEncode({'channel': channel, 'preview_hash': previewHash, 'consent_confirmed': true}));
    if (response.statusCode != 200) throw ApiException(response.body);
  }

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
      // The reason, not the raw body. A worker whose registration is
      // simply unapproved was being shown a JSON blob on her login screen.
      throw ApiException(_detail(resp.body) ?? 'Login failed', status: resp.statusCode);
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    _token = data['access_token'] as String;
    return data;
  }

  /// Her own record: code, sub-centre, counts, and any leave arranged.
  Future<Map<String, dynamic>> fetchMyProfile() async {
    final resp = await http.get(Uri.parse('$baseUrl/api/v1/workers/me'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException(_detail(resp.body) ?? 'Failed to load profile', status: resp.statusCode);
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  /// The other ASHAs in her sub-centre -- the people who could cover for
  /// her. Names and codes only; a peer is not owed a staff directory.
  Future<List<Map<String, dynamic>>> fetchColleagues() async {
    final resp = await http.get(Uri.parse('$baseUrl/api/v1/workers/colleagues'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException(_detail(resp.body) ?? 'Failed to load colleagues', status: resp.statusCode);
    }
    return (jsonDecode(resp.body) as List).cast<Map<String, dynamic>>();
  }

  /// "I am away until the 20th, and Kavita is covering."
  ///
  /// Not a transfer: the patients stay hers. See the WorkerAbsence model
  /// for why that distinction is the whole design.
  Future<Map<String, dynamic>> declareLeave({
    required String coveringWorkerId,
    required DateTime startsOn,
    required DateTime endsOn,
    String? reason,
  }) async {
    String day(DateTime d) => d.toIso8601String().split('T').first;
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/workers/me/absence'),
      headers: _headers,
      body: jsonEncode({
        'covering_worker_id': coveringWorkerId,
        'starts_on': day(startsOn),
        'ends_on': day(endsOn),
        'reason': reason,
      }),
    );
    if (resp.statusCode != 201) {
      throw ApiException(_detail(resp.body) ?? 'Could not arrange cover', status: resp.statusCode);
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  /// She is back early.
  Future<void> endLeave(String absenceId) async {
    final resp = await http.delete(
      Uri.parse('$baseUrl/api/v1/workers/me/absence/$absenceId'),
      headers: _headers,
    );
    if (resp.statusCode != 200) {
      throw ApiException(_detail(resp.body) ?? 'Could not end that', status: resp.statusCode);
    }
  }

  /// Ask for an account. Returns no token: registering is a request, and
  /// an admin has to approve it before she can sign in.
  Future<Map<String, dynamic>> register({
    required String name,
    required String phone,
    required String pin,
    required String role,
    String? subCentreId,
    String languagePref = 'hi',
  }) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/auth/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'phone': phone,
        'pin': pin,
        'role': role,
        'sub_centre_id': subCentreId,
        'language_pref': languagePref,
      }),
    );
    if (resp.statusCode != 201) {
      throw ApiException(_detail(resp.body) ?? 'Registration failed', status: resp.statusCode);
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  /// Change your own PIN. The current one is required, so an unlocked
  /// phone left on a table is not an account takeover.
  Future<void> changePin({required String currentPin, required String newPin}) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/auth/change-pin'),
      headers: _headers,
      body: jsonEncode({'current_pin': currentPin, 'new_pin': newPin}),
    );
    if (resp.statusCode != 204) {
      throw ApiException(_detail(resp.body) ?? 'Could not change the PIN', status: resp.statusCode);
    }
  }

  /// FastAPI puts the human-readable reason in `detail`. Without pulling it
  /// out, an ASHA whose registration is simply unapproved gets a raw JSON
  /// body on her login screen and no idea what to do about it.
  static String? _detail(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map && decoded['detail'] is String) return decoded['detail'] as String;
    } catch (_) {
      // Not JSON. Fall through to the caller's own message.
    }
    return null;
  }

  /// Trade the stored token for a fresh one, so time offline never runs it
  /// out (FR-07.1). Called on every online app start. A failure here is not
  /// something the worker should ever be shown: the token she already holds
  /// is still valid until it isn't, and the next start will try again.
  Future<Map<String, dynamic>> refreshToken() async {
    final resp = await http.post(Uri.parse('$baseUrl/api/v1/auth/refresh'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException('Refresh failed: ${resp.body}');
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    _token = data['access_token'] as String;
    return data;
  }

  /// Who she can ring when she is stuck: her ANM, and the block office.
  /// Server-side rather than baked into the app, because the ANM covering
  /// a sub-centre changes and a number shipped in a release goes stale.
  Future<List<Map<String, dynamic>>> fetchSupportContacts() async {
    final resp = await http.get(Uri.parse('$baseUrl/api/v1/support/contacts'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException('Failed to load contacts: ${resp.body}');
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    return (data['contacts'] as List).cast<Map<String, dynamic>>();
  }

  /// Report a problem with the app itself. Needs signal -- deliberately not
  /// queued offline: a bug report that arrives three days late is worth
  /// much less than the honest "send this when you have bars" message.
  Future<Map<String, dynamic>> reportProblem({
    required String category,
    required String message,
    String? appVersion,
    String? deviceInfo,
    String? language,
  }) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/support/tickets'),
      headers: _headers,
      body: jsonEncode({
        'category': category,
        'message': message,
        'app_version': appVersion,
        'device_info': deviceInfo,
        'language': language,
      }),
    );
    if (resp.statusCode != 201) {
      throw ApiException('Could not send report: ${resp.body}');
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  /// What she has reported, and whether anybody answered. Without this the
  /// Help screen is a suggestion box with no bottom.
  Future<List<Map<String, dynamic>>> fetchMyReports() async {
    final resp = await http.get(
      Uri.parse('$baseUrl/api/v1/support/tickets/mine'),
      headers: _headers,
    );
    if (resp.statusCode != 200) {
      throw ApiException('Failed to load reports: ${resp.body}');
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    return (data['tickets'] as List).cast<Map<String, dynamic>>();
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
    String? rchNumber,
    int? bpSystolic,
    int? bpDiastolic,
    int? bloodSugarFasting,
    int? bloodSugarRandom,
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
        'rch_number': rchNumber,
        'bp_systolic': bpSystolic,
        'bp_diastolic': bpDiastolic,
        'blood_sugar_fasting': bloodSugarFasting,
        'blood_sugar_random': bloodSugarRandom,
      }),
    );
    if (resp.statusCode != 201) {
      // 409 is the duplicate check: this woman is already on somebody's
      // list. The reason matters -- "Failed to add patient" plus a JSON
      // blob taught her nothing and she would simply type it again.
      throw ApiException(
        _detail(resp.body) ?? 'Failed to add patient: ${resp.body}',
        status: resp.statusCode,
      );
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
    // Keep the answer for the next time she opens this in a village with
    // no signal. Written before parsing, and deliberately not awaited into
    // the failure path: a cache that will not save must never cost her the
    // list she just successfully fetched.
    unawaited(PatientCache.save(workerId, resp.body).catchError((_) {}));
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

  /// The same review-before-trust step as [transcribeAudio], one level
  /// down: pull the clinical fields out of the transcript she just
  /// confirmed, so a misheard BP can be corrected before it becomes a risk
  /// classification. Read-only on the backend -- nothing is stored until
  /// [submitVoiceVisit] is called with the corrected values.
  Future<Map<String, dynamic>> extractFields({required String transcript}) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/visits/extract'),
      headers: _headers,
      body: jsonEncode({'transcript': transcript}),
    );
    if (resp.statusCode != 200) {
      throw ApiException('Could not read the details: ${_readableError(resp.body)}');
    }
    return (jsonDecode(resp.body) as Map<String, dynamic>)['extracted'] as Map<String, dynamic>;
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
    Map<String, dynamic>? confirmedExtracted,
    String? clientRequestId,
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
        if (confirmedExtracted != null) 'confirmed_extracted': confirmedExtracted,
        if (clientRequestId != null) 'client_request_id': clientRequestId,
      }),
    );
    if (resp.statusCode != 200) {
      throw ApiException('Voice visit failed: ${resp.body}');
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  /// FR-07.3: pending follow-up tasks, sorted by urgency by the backend.
  ///
  /// Returns the whole board, not just the flat list: the server also
  /// buckets each task as overdue / due today / upcoming against the
  /// deadline Agent 3 set for that patient's risk level, and the home
  /// screen shows today's work from it. Classifying here instead would
  /// risk the app and her supervisor's dashboard disagreeing about
  /// whether a visit was missed.
  Future<Map<String, dynamic>> fetchTaskBoard(String workerId) async {
    final resp = await http.get(Uri.parse('$baseUrl/api/v1/tasks/$workerId'), headers: _headers);
    if (resp.statusCode != 200) {
      throw ApiException('Failed to load tasks: ${resp.body}');
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> fetchTasks(String workerId) async {
    final board = await fetchTaskBoard(workerId);
    return (board['tasks'] as List).cast<Map<String, dynamic>>();
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

  /// FR-03.3: correct the AI's risk call on a visit with a mandatory
  /// reason. An ASHA can do this for her own visits only -- the backend
  /// enforces that (and the wider sub-centre/district rules for ANM/BMO,
  /// who use this same endpoint from the web dashboard) and returns a 403
  /// with a plain-language reason if it's not allowed.
  Future<Map<String, dynamic>> overrideRisk({
    required String visitId,
    required String newRiskLevel,
    required String reason,
  }) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/v1/visits/$visitId/risk-override'),
      headers: _headers,
      body: jsonEncode({'new_risk_level': newRiskLevel, 'reason': reason}),
    );
    if (resp.statusCode != 200) {
      throw ApiException(_readableError(resp.body));
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  /// FastAPI error bodies are JSON ({"detail": "..."} or, for a 422
  /// validation failure, {"detail": [{"msg": "...", ...}, ...]}) -- pull
  /// out just the message instead of showing raw JSON in a SnackBar.
  String _readableError(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map && decoded['detail'] is String) {
        return decoded['detail'] as String;
      }
      if (decoded is Map && decoded['detail'] is List && (decoded['detail'] as List).isNotEmpty) {
        final first = (decoded['detail'] as List).first;
        if (first is Map && first['msg'] != null) return first['msg'].toString();
      }
    } catch (_) {
      // Not JSON (or not the shape we expect) -- fall through to raw body.
    }
    return body;
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

  /// The HTTP status, when the caller needs to tell one refusal from
  /// another -- 403 on login means "waiting for approval", 401 means the
  /// PIN is wrong, and those two want very different things said to her.
  final int? status;

  ApiException(this.message, {this.status});

  @override
  String toString() => message;
}
