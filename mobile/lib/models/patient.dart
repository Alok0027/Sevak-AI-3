/// Mirrors GET /api/v1/patients/{worker_id} response items (FR-07.2).
class Patient {
  final String id;
  final String name;
  final int? age;
  final String? village;
  final String? pregnancyStage;
  final String? riskStatus; // HIGH | MEDIUM | LOW | null (no visit yet)
  final DateTime? lastVisit;
  final int totalVisits;

  Patient({
    required this.id,
    required this.name,
    this.age,
    this.village,
    this.pregnancyStage,
    this.riskStatus,
    this.lastVisit,
    this.totalVisits = 0,
  });

  factory Patient.fromJson(Map<String, dynamic> json) => Patient(
        id: json['id'] as String,
        name: json['name'] as String,
        age: json['age'] as int?,
        village: json['village'] as String?,
        pregnancyStage: json['pregnancy_stage'] as String?,
        riskStatus: json['risk_status'] as String?,
        lastVisit: json['last_visit'] != null ? DateTime.parse(json['last_visit'] as String) : null,
        totalVisits: json['total_visits'] as int? ?? 0,
      );
}
