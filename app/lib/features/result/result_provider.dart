/// Manages the PDF download and local path once a job is done.
library;

import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../../core/network/api_client.dart';
import '../../core/network/api_exception.dart';

// ── Result state ──────────────────────────────────────────────────────────────

class ResultState {
  const ResultState({
    required this.jobId,
    required this.downloadToken,
    this.isDownloading = false,
    this.downloadProgress = 0.0,
    this.localPath,
    this.error,
  });

  final String jobId;
  final String downloadToken;
  final bool isDownloading;
  final double downloadProgress; // 0.0 – 1.0
  final String? localPath;        // set when download completes
  final String? error;

  bool get hasFile => localPath != null;

  ResultState copyWith({
    bool? isDownloading,
    double? downloadProgress,
    String? localPath,
    String? error,
    bool clearError = false,
  }) {
    return ResultState(
      jobId: jobId,
      downloadToken: downloadToken,
      isDownloading: isDownloading ?? this.isDownloading,
      downloadProgress: downloadProgress ?? this.downloadProgress,
      localPath: localPath ?? this.localPath,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

// ── Notifier ──────────────────────────────────────────────────────────────────

class ResultNotifier extends StateNotifier<ResultState> {
  ResultNotifier(this._api, String jobId, String token)
      : super(ResultState(jobId: jobId, downloadToken: token));

  final ApiClient _api;

  Future<void> download() async {
    if (state.isDownloading || state.hasFile) return;

    state = state.copyWith(isDownloading: true, clearError: true);

    try {
      final dir = await getApplicationDocumentsDirectory();
      final savePath = '${dir.path}/handprint_${state.jobId}.pdf';

      await _api.downloadResult(
        jobId: state.jobId,
        token: state.downloadToken,
        savePath: savePath,
        onProgress: (received, total) {
          if (total > 0) {
            state = state.copyWith(downloadProgress: received / total);
          }
        },
      );

      state = state.copyWith(
        isDownloading: false,
        localPath: savePath,
        downloadProgress: 1.0,
      );
    } on DioException catch (e) {
      final ex = e.error is ApiException
          ? e.error as ApiException
          : ApiException(message: e.message ?? 'Download failed.');
      state = state.copyWith(isDownloading: false, error: ex.toString());
    } catch (e) {
      state = state.copyWith(isDownloading: false, error: e.toString());
    }
  }

  void clearError() => state = state.copyWith(clearError: true);
}

// ── Provider (family — keyed by jobId:token) ──────────────────────────────────

final resultProvider = StateNotifierProvider.autoDispose
    .family<ResultNotifier, ResultState, (String, String)>(
  (ref, args) {
    final (jobId, token) = args;
    return ResultNotifier(ref.watch(apiClientProvider), jobId, token);
  },
);
