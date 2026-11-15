/// Result provider — downloads the finished PDF and manages the local file.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/network/api_client.dart';
import '../history/history_provider.dart';
import '../settings/settings_provider.dart';

class ResultState {
  const ResultState({
    this.isDownloading = false,
    this.downloadProgress = 0.0,
    this.localPath,
    this.error,
  });

  final bool isDownloading;
  final double downloadProgress; // 0.0–1.0
  final String? localPath;       // set when download completes
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
      isDownloading: isDownloading ?? this.isDownloading,
      downloadProgress: downloadProgress ?? this.downloadProgress,
      localPath: localPath ?? this.localPath,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

class ResultNotifier extends StateNotifier<ResultState> {
  ResultNotifier(this._api, this._ref) : super(const ResultState());

  final ApiClient _api;
  final Ref _ref;

  /// Download the finished PDF for [jobId] to the app's documents directory.
  Future<String?> download(String jobId) async {
    if (state.isDownloading || state.hasFile) return state.localPath;

    state = state.copyWith(
      isDownloading: true,
      downloadProgress: 0.0,
      clearError: true,
    );

    try {
      final dir = await getApplicationDocumentsDirectory();
      final savePath = '${dir.path}/handprint_$jobId.pdf';

      await _api.downloadResult(
        jobId: jobId,
        savePath: savePath,
        onProgress: (progress) {
          state = state.copyWith(downloadProgress: progress);
        },
      );

      state = state.copyWith(
        isDownloading: false,
        downloadProgress: 1.0,
        localPath: savePath,
      );

      // Record in history so the History tab shows completed conversions.
      await _ref.read(historyProvider.notifier).add(HistoryEntry(
        jobId: jobId,
        profileName: '',
        completedAt: DateTime.now(),
        localPath: savePath,
        pdfFileName: 'handprint_$jobId.pdf',
      ));

      return savePath;
    } catch (e) {
      state = state.copyWith(
        isDownloading: false,
        error: e.toString(),
      );
      return null;
    }
  }

  /// Share the downloaded PDF via the platform share sheet.
  Future<void> share() async {
    if (state.localPath == null) return;
    await Share.shareXFiles(
      [XFile(state.localPath!)],
      text: 'Handwritten PDF from Handprint AI',
    );
  }

  void reset() {
    state = const ResultState();
  }

  void clearError() {
    state = state.copyWith(clearError: true);
  }
}

final resultProvider =
    StateNotifierProvider.autoDispose.family<ResultNotifier, ResultState, String>(
  (ref, jobId) {
    final api = ref.watch(settingsApiClientProvider);
    return ResultNotifier(api, ref);
  },
);
