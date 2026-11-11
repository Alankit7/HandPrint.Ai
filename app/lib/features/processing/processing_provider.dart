/// Polls the backend for job status updates.
library;

import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';
import '../../core/models/job_status.dart';
import '../../core/network/api_client.dart';
import '../../core/network/api_exception.dart';

// ── Processing state ──────────────────────────────────────────────────────────

class ProcessingState {
  const ProcessingState({
    required this.jobId,
    this.status = JobStatus.pending,
    this.progress = 0.0,
    this.message = 'Waiting…',
    this.downloadToken,
    this.error,
  });

  final String jobId;
  final JobStatus status;
  final double progress;
  final String message;
  final String? downloadToken; // available when status == done
  final String? error;

  bool get isDone => status == JobStatus.done;
  bool get isFailed => status == JobStatus.failed;
  bool get isTerminal => status.isTerminal;

  ProcessingState copyWith({
    JobStatus? status,
    double? progress,
    String? message,
    String? downloadToken,
    String? error,
  }) {
    return ProcessingState(
      jobId: jobId,
      status: status ?? this.status,
      progress: progress ?? this.progress,
      message: message ?? this.message,
      downloadToken: downloadToken ?? this.downloadToken,
      error: error ?? this.error,
    );
  }
}

// ── Notifier ──────────────────────────────────────────────────────────────────

class ProcessingNotifier extends StateNotifier<ProcessingState> {
  ProcessingNotifier(this._api, String jobId)
      : super(ProcessingState(jobId: jobId)) {
    _startPolling();
  }

  final ApiClient _api;
  Timer? _timer;

  void _startPolling() {
    _timer = Timer.periodic(AppConfig.pollInterval, (_) => _poll());
    _poll(); // Immediate first check
  }

  Future<void> _poll() async {
    if (state.isTerminal) {
      _timer?.cancel();
      return;
    }

    try {
      final json = await _api.getJobStatus(state.jobId);
      final response = JobStatusResponse.fromJson(json);
      state = state.copyWith(
        status: response.status,
        progress: response.progress,
        message: response.message,
        downloadToken: response.downloadToken,
      );

      if (state.isTerminal) {
        _timer?.cancel();
      }
    } on DioException catch (e) {
      final ex = e.error is ApiException
          ? e.error as ApiException
          : ApiException(message: e.message ?? 'Polling failed.');
      // Soft error — keep polling unless it's a hard 404
      if (ex.statusCode == 404) {
        _timer?.cancel();
        state = state.copyWith(
          status: JobStatus.failed,
          error: 'Job not found on server.',
        );
      }
      // Other transient network errors are silently retried next tick
    } catch (e) {
      // Ignore transient errors; will retry
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

// ── Provider (family — keyed by job_id) ──────────────────────────────────────

final processingProvider = StateNotifierProvider.autoDispose
    .family<ProcessingNotifier, ProcessingState, String>(
  (ref, jobId) => ProcessingNotifier(ref.watch(apiClientProvider), jobId),
);
