/// Job model matching the backend JobResponse schema.
library;

enum JobStatus { queued, processing, done, failed }

extension JobStatusX on JobStatus {
  static JobStatus fromString(String s) => switch (s) {
        'queued' => JobStatus.queued,
        'processing' => JobStatus.processing,
        'done' => JobStatus.done,
        'failed' => JobStatus.failed,
        _ => JobStatus.queued,
      };

  bool get isTerminal => this == JobStatus.done || this == JobStatus.failed;
  bool get isActive => this == JobStatus.queued || this == JobStatus.processing;
  String get label => switch (this) {
        JobStatus.queued => 'Queued',
        JobStatus.processing => 'Processing',
        JobStatus.done => 'Done',
        JobStatus.failed => 'Failed',
      };
}

class Job {
  const Job({
    required this.id,
    required this.profileId,
    required this.status,
    required this.progress,
    required this.message,
    this.error,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String profileId;
  final JobStatus status;
  final double progress;
  final String message;
  final String? error;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory Job.fromJson(Map<String, dynamic> json) {
    return Job(
      id: json['id'] as String,
      profileId: json['profile_id'] as String,
      status: JobStatusX.fromString(json['status'] as String),
      progress: (json['progress'] as num).toDouble(),
      message: json['message'] as String? ?? '',
      error: json['error'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
    );
  }
}
