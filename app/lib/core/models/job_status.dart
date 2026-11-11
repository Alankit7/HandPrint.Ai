/// Mirrors the backend JobStatus enum and JobStatusResponse schema.
library;

enum JobStatus { pending, processing, done, failed }

extension JobStatusX on JobStatus {
  static JobStatus fromString(String s) => switch (s) {
        'pending' => JobStatus.pending,
        'processing' => JobStatus.processing,
        'done' => JobStatus.done,
        'failed' => JobStatus.failed,
        _ => JobStatus.pending,
      };

  bool get isTerminal => this == JobStatus.done || this == JobStatus.failed;
  bool get isActive => this == JobStatus.pending || this == JobStatus.processing;
}

class JobStatusResponse {
  const JobStatusResponse({
    required this.jobId,
    required this.status,
    required this.progress,
    required this.message,
    this.downloadToken,
  });

  final String jobId;
  final JobStatus status;
  final double progress; // 0.0 – 1.0
  final String message;
  final String? downloadToken;

  factory JobStatusResponse.fromJson(Map<String, dynamic> json) {
    return JobStatusResponse(
      jobId: json['job_id'] as String,
      status: JobStatusX.fromString(json['status'] as String),
      progress: (json['progress'] as num).toDouble(),
      message: json['message'] as String? ?? '',
      downloadToken: json['download_token'] as String?,
    );
  }
}
