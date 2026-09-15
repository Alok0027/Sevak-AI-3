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

  /// Triage, decided on the server (backend/app/services/patient_priority.py)
  /// so an ASHA and the ANM supervising her can never be looking at
  /// differently-ordered copies of the same ward.
  ///
  /// [needsAttention] answers "is this mine to do today", which is a
  /// different question from "how bad is it" -- an overdue LOW is a broken
  /// promise even though she is well. The server's ordering answers the
  /// other one; the list simply keeps the order it was given.
  final bool needsAttention;
  final String? attentionReason; // high_risk | overdue | due_today
  final int hoursOverdue;

  Patient({
    required this.id,
    required this.name,
    this.age,
    this.village,
    this.pregnancyStage,
    this.riskStatus,
    this.lastVisit,
    this.totalVisits = 0,
    this.needsAttention = false,
    this.attentionReason,
    this.hoursOverdue = 0,
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
        // Defaulted, not required: an app build newer than the server it is
        // talking to still shows the list, just without the grouping.
        needsAttention: json['needs_attention'] as bool? ?? false,
        attentionReason: json['attention_reason'] as String?,
        hoursOverdue: json['hours_overdue'] as int? ?? 0,
      );
}
