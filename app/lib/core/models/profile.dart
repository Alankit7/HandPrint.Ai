/// Profile model matching the backend ProfileResponse schema.
library;

enum ProfileStatus { pending, training, ready, failed }

extension ProfileStatusX on ProfileStatus {
  static ProfileStatus fromString(String s) => switch (s) {
        'pending' => ProfileStatus.pending,
        'training' => ProfileStatus.training,
        'ready' => ProfileStatus.ready,
        'failed' => ProfileStatus.failed,
        _ => ProfileStatus.pending,
      };

  bool get isTerminal => this == ProfileStatus.ready || this == ProfileStatus.failed;
  bool get isActive => this == ProfileStatus.training;
  String get label => switch (this) {
        ProfileStatus.pending => 'Pending',
        ProfileStatus.training => 'Training',
        ProfileStatus.ready => 'Ready',
        ProfileStatus.failed => 'Failed',
      };
}

class Profile {
  const Profile({
    required this.id,
    required this.name,
    required this.status,
    required this.sampleCount,
    required this.trainProgress,
    this.error,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String name;
  final ProfileStatus status;
  final int sampleCount;
  final double trainProgress;
  final String? error;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory Profile.fromJson(Map<String, dynamic> json) {
    return Profile(
      id: json['id'] as String,
      name: json['name'] as String,
      status: ProfileStatusX.fromString(json['status'] as String),
      sampleCount: (json['sample_count'] as num).toInt(),
      trainProgress: (json['train_progress'] as num).toDouble(),
      error: json['error'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
    );
  }
}
