/// Convert provider — submit PDF conversion job and poll status until terminal.
///
/// Polling logic:
///   1. submit() uploads the PDF and gets a job_id.
///   2. A Timer.periodic polls GET /jobs/{id} every POLL_INTERVAL_SECONDS.
///   3. When status is done/failed the timer is cancelled.
///   4. Progress and message are exposed through ConvertState.
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';
import '../../core/models/job.dart';
import '../../core/network/api_client.dart';
import '../settings/settings_provider.dart';

// ── State ──────────────────────────────────────────────────────────────────────

class ConvertState {
  const ConvertState({
    this.isUploading = false,
    this.uploadProgress = 0.0,
    this.jobId,
    this.job,
    this.error,
  });

  final bool isUploading;
  final double uploadProgress; // 0.0–1.0 during upload
  final String? jobId;
  final Job? job;              // null until first poll succeeds
  final String? error;

  bool get isPolling => jobId != null && job != null && job!.status.isActive;
  bool get isDone => job != null && job!.status == JobStatus.done;
  bool get isFailed => job != null && job!.status == JobStatus.failed;
  bool get isBusy => isUploading || isPolling;

  ConvertState copyWith({
    bool? isUploading,
    double? uploadProgress,
    String? jobId,
    Job? job,
    String? error,
    bool clearError = false,
    bool clearJob = false,
  }) {
    return ConvertState(
      isUploading: isUploading ?? this.isUploading,
      uploadProgress: uploadProgress ?? this.uploadProgress,
      jobId: clearJob ? null : (jobId ?? this.jobId),
      job: clearJob ? null : (job ?? this.job),
      error: clearError ? null : (error ?? this.error),
    );
  }
}

// ── Notifier ──────────────────────────────────────────────────────────────────

class ConvertNotifier extends StateNotifier<ConvertState> {
  ConvertNotifier(this._api) : super(const ConvertState());

  final ApiClient _api;
  Timer? _pollTimer;

  /// Upload PDF and start polling the job status.
  ///
  /// Returns the job_id on success, null on failure.
  Future<String?> submit({
    required String profileId,
    required String pdfPath,
    String? paperStyle,
    String? inkColor,
    double? jitter,
  }) async {
    // ── Upload phase ──────────────────────────────────────────────────────
    state = const ConvertState();
    state = state.copyWith(
      isUploading: true,
      uploadProgress: 0.0,
      clearError: true,
    );

    try {
      final job = await _api.convert(
        profileId: profileId,
        pdfPath: pdfPath,
        paperStyle: paperStyle,
        inkColor: inkColor,
        jitter: jitter,
        onProgress: (p) {
          state = state.copyWith(uploadProgress: p);
        },
      );
      state = state.copyWith(
        isUploading: false,
        uploadProgress: 1.0,
        jobId: job.id,
        job: job,
      );
      // ── Start polling ────────────────────────────────────────────────────
      _startPolling(job.id);
      return job.id;
    } catch (e) {
      state = state.copyWith(
        isUploading: false,
        error: e.toString(),
      );
      return null;
    }
  }

  /// Poll GET /jobs/{id} once and update state.
  /// Exposed for testing so the polling logic can be exercised without a timer.
  Future<void> poll(String jobId) async {
    try {
      final job = await _api.getJob(jobId);
      state = state.copyWith(job: job);

      if (job.status.isTerminal) {
        _pollTimer?.cancel();
        _pollTimer = null;
      }
    } catch (e) {
      // Don't overwrite the job on transient errors — keep the last known state.
      // Only set error if we have no job yet.
      if (state.job == null) {
        state = state.copyWith(error: e.toString());
      }
    }
  }

  void _startPolling(String jobId) {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(
      Duration(seconds: AppConfig.pollIntervalSeconds),
      (_) => poll(jobId),
    );
    // Immediate first poll
    poll(jobId);
  }

  void stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  void reset() {
    _pollTimer?.cancel();
    _pollTimer = null;
    state = const ConvertState();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }
}

// ── Provider ──────────────────────────────────────────────────────────────────

final convertProvider =
    StateNotifierProvider.autoDispose<ConvertNotifier, ConvertState>(
  (ref) {
    final api = ref.watch(settingsApiClientProvider);
    return ConvertNotifier(api);
  },
);
