/// Manages PDF + sample selection and job submission.
library;

import 'dart:io';

import 'package:dio/dio.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';
import '../../core/models/job_submission.dart';
import '../../core/network/api_client.dart';
import '../../core/network/api_exception.dart';

// ── Upload state ──────────────────────────────────────────────────────────────

class UploadState {
  const UploadState({
    this.pdfPath,
    this.samplePaths = const [],
    this.isSubmitting = false,
    this.error,
    this.submittedJobId,
  });

  final String? pdfPath;
  final List<String> samplePaths;
  final bool isSubmitting;
  final String? error;
  final String? submittedJobId; // set after a successful POST /jobs

  bool get hasPdf => pdfPath != null;
  bool get hasSamples => samplePaths.isNotEmpty;
  bool get canSubmit => hasPdf && hasSamples && !isSubmitting;

  String get pdfName => pdfPath?.split('/').last ?? '';

  UploadState copyWith({
    String? pdfPath,
    List<String>? samplePaths,
    bool? isSubmitting,
    String? error,
    String? submittedJobId,
    bool clearError = false,
    bool clearJob = false,
  }) {
    return UploadState(
      pdfPath: pdfPath ?? this.pdfPath,
      samplePaths: samplePaths ?? this.samplePaths,
      isSubmitting: isSubmitting ?? this.isSubmitting,
      error: clearError ? null : (error ?? this.error),
      submittedJobId: clearJob ? null : (submittedJobId ?? this.submittedJobId),
    );
  }
}

// ── Notifier ──────────────────────────────────────────────────────────────────

class UploadNotifier extends StateNotifier<UploadState> {
  UploadNotifier(this._api) : super(const UploadState());

  final ApiClient _api;

  /// Open the system file picker and store the selected PDF path.
  Future<void> pickPdf() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf'],
      allowMultiple: false,
    );
    if (result == null || result.files.isEmpty) return;

    final file = result.files.single;
    final path = file.path;
    if (path == null) return;

    // Size check
    final fileSize = await File(path).length();
    if (fileSize > AppConfig.maxPdfSizeBytes) {
      state = state.copyWith(
        error: 'PDF exceeds the ${AppConfig.maxPdfSizeMb} MB limit.',
      );
      return;
    }

    state = state.copyWith(pdfPath: path, clearError: true);
  }

  /// Open the system file picker for handwriting sample images.
  Future<void> pickSamples() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.image,
      allowMultiple: true,
    );
    if (result == null || result.files.isEmpty) return;

    final paths = result.files
        .map((f) => f.path)
        .whereType<String>()
        .toList();

    if (paths.isEmpty) return;

    state = state.copyWith(samplePaths: paths, clearError: true);
  }

  void removePdf() => state = state.copyWith(pdfPath: null, clearError: true);

  void removeSample(int index) {
    final updated = List<String>.from(state.samplePaths)..removeAt(index);
    state = state.copyWith(samplePaths: updated);
  }

  void clearError() => state = state.copyWith(clearError: true);

  /// Submit the job to the API and return the job_id on success.
  Future<String?> submit() async {
    if (!state.canSubmit) return null;

    state = state.copyWith(isSubmitting: true, clearError: true);
    try {
      final json = await _api.createJob(
        pdfPath: state.pdfPath!,
        samplePaths: state.samplePaths,
      );
      final jobId = json['job_id'] as String;
      state = state.copyWith(isSubmitting: false, submittedJobId: jobId);
      return jobId;
    } on DioException catch (e) {
      final ex = e.error is ApiException
          ? e.error as ApiException
          : ApiException(message: e.message ?? 'Upload failed.');
      state = state.copyWith(isSubmitting: false, error: ex.toString());
      return null;
    } catch (e) {
      state = state.copyWith(isSubmitting: false, error: e.toString());
      return null;
    }
  }

  /// Reset the entire upload form.
  void reset() => state = const UploadState();
}

// ── Provider ──────────────────────────────────────────────────────────────────

final uploadProvider =
    StateNotifierProvider.autoDispose<UploadNotifier, UploadState>(
  (ref) => UploadNotifier(ref.watch(apiClientProvider)),
);
