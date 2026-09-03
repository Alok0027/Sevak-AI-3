/// Real, backend-computed aggregates for one worker -- mirrors
/// GET /api/v1/workers/{worker_id}/history's `worker` object (FR-08
/// "worker performance metrics"). Backs the ASHA home screen's stat cards.
class WorkerStats {
  final String workerId;
  final String name;
  final String phone;
  final String? subCentreId;
  final String languagePref;
  final int totalPatients;
  final int totalVisits;
  final int highRiskCount;
  final int mediumRiskCount;
  final int lowRiskCount;
  final int pendingFollowups;
  final DateTime? lastVisitAt;

  WorkerStats({
    required this.workerId,
    required this.name,
    required this.phone,
    required this.subCentreId,
    required this.languagePref,
    required this.totalPatients,
    required this.totalVisits,
    required this.highRiskCount,
    required this.mediumRiskCount,
    required this.lowRiskCount,
    required this.pendingFollowups,
    required this.lastVisitAt,
  });

  factory WorkerStats.fromJson(Map<String, dynamic> json) => WorkerStats(
        workerId: json['worker_id'] as String,
        name: json['name'] as String,
        phone: json['phone'] as String,
        subCentreId: json['sub_centre_id'] as String?,
        languagePref: json['language_pref'] as String,
        totalPatients: json['total_patients'] as int,
        totalVisits: json['total_visits'] as int,
        highRiskCount: json['high_risk_count'] as int,
        mediumRiskCount: json['medium_risk_count'] as int,
        lowRiskCount: json['low_risk_count'] as int,
        pendingFollowups: json['pending_followups'] as int,
        lastVisitAt: json['last_visit_at'] != null ? DateTime.parse(json['last_visit_at'] as String) : null,
      );
}

/// One entry in a worker's or patient's visit timeline -- transcript plus
/// the full extracted structured record, straight from the backend.
class VisitEntry {
  final String visitId;
  final String patientId;
  final String patientName;
  final DateTime createdAt;
  final String? riskLevel;
  final String? transcript;
  final Map<String, dynamic>? extracted;

  VisitEntry({
    required this.visitId,
    required this.patientId,
    required this.patientName,
    required this.createdAt,
    required this.riskLevel,
    required this.transcript,
    required this.extracted,
  });

  factory VisitEntry.fromJson(Map<String, dynamic> json) => VisitEntry(
        visitId: json['visit_id'] as String,
        patientId: json['patient_id'] as String,
        patientName: json['patient_name'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        riskLevel: json['risk_level'] as String?,
        transcript: json['transcript'] as String?,
        extracted: json['extracted'] as Map<String, dynamic>?,
      );
}

/// GET /api/v1/workers/{worker_id}/history response.
class WorkerHistory {
  final WorkerStats worker;
  final List<VisitEntry> visits;

  WorkerHistory({required this.worker, required this.visits});

  factory WorkerHistory.fromJson(Map<String, dynamic> json) => WorkerHistory(
        worker: WorkerStats.fromJson(json['worker'] as Map<String, dynamic>),
        visits: (json['visits'] as List)
            .map((v) => VisitEntry.fromJson(v as Map<String, dynamic>))
            .toList(),
      );
}

/// GET /api/v1/patients/{patient_id}/history response.
class PatientHistory {
  final String patientId;
  final String patientName;
  final String workerId;
  final String workerName;
  final String? village;
  final int? age;
  final String? pregnancyStage;
  final List<VisitEntry> visits;

  PatientHistory({
    required this.patientId,
    required this.patientName,
    required this.workerId,
    required this.workerName,
    required this.village,
    required this.age,
    required this.pregnancyStage,
    required this.visits,
  });

  factory PatientHistory.fromJson(Map<String, dynamic> json) => PatientHistory(
        patientId: json['patient_id'] as String,
        patientName: json['patient_name'] as String,
        workerId: json['worker_id'] as String,
        workerName: json['worker_name'] as String,
        village: json['village'] as String?,
        age: json['age'] as int?,
        pregnancyStage: json['pregnancy_stage'] as String?,
        visits: (json['visits'] as List)
            .map((v) => VisitEntry.fromJson(v as Map<String, dynamic>))
            .toList(),
      );
}
