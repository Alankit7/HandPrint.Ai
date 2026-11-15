/// Typed Dio HTTP client matching every backend endpoint.
///
/// Endpoints (all except /health require X-API-Key header):
///   POST   /profiles               — create profile (multipart: name + images)
///   POST   /profiles/{id}/train     — start fine-tuning
///   GET    /profiles/{id}           — profile status + train progress
///   POST   /convert                 — submit conversion (multipart: profile_id + pdf)
///   GET    /jobs/{id}               — job status + render progress
///   GET    /download/{id}           — download finished PDF (binary)
///   GET    /health                  — liveness check (no auth)
library;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/job.dart';
import '../models/profile.dart';
import 'api_exception.dart';

/// A factory provider that accepts base URL and API key.
final apiClientFactoryProvider =
    Provider.family<ApiClient, ({String baseUrl, String apiKey})>(
  (ref, args) => ApiClient(baseUrl: args.baseUrl, apiKey: args.apiKey),
);

class ApiClient {
  ApiClient({required this.baseUrl, required this.apiKey})
      : _dio = Dio(
          BaseOptions(
            baseUrl: baseUrl,
            connectTimeout: const Duration(seconds: 30),
            receiveTimeout: const Duration(minutes: 10),
            sendTimeout: const Duration(minutes: 5),
            headers: {
              'X-API-Key': apiKey,
              'Accept': 'application/json',
            },
          ),
        );

  final String baseUrl;
  final String apiKey;
  final Dio _dio;

  // ── Profiles ─────────────────────────────────────────────────────────────

  /// POST /profiles — upload sample images and create a profile.
  ///
  /// [name] is the writer name. [samplePaths] are absolute file paths to
  /// 15–30 handwriting sample images. [onProgress] reports upload progress
  /// as a fraction 0.0–1.0.
  Future<Profile> createProfile({
    required String name,
    required List<String> samplePaths,
    void Function(double progress)? onProgress,
  }) async {
    final form = FormData();
    form.fields.add(MapEntry('name', name));
    for (final path in samplePaths) {
      form.files.add(MapEntry(
        'images',
        await MultipartFile.fromFile(path, filename: path.split('/').last),
      ));
    }
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/profiles',
        data: form,
        onSendProgress: (sent, total) {
          if (total > 0 && onProgress != null) {
            onProgress(sent / total);
          }
        },
      );
      return Profile.fromJson(response.data!);
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  /// POST /profiles/{id}/train — start fine-tuning.
  Future<void> startTraining(String profileId) async {
    try {
      await _dio.post('/profiles/$profileId/train');
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  /// GET /profiles/{id} — poll training status.
  Future<Profile> getProfile(String profileId) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>('/profiles/$profileId');
      return Profile.fromJson(response.data!);
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  // ── Convert / Jobs ──────────────────────────────────────────────────────────

  /// POST /convert — submit a conversion job.
  ///
  /// [profileId] must reference a READY profile. [pdfPath] is the absolute
  /// path to the source PDF. [onProgress] reports upload progress.
  /// [paperStyle], [inkColor], [jitter] are optional render preferences
  /// sent as extra form fields (backend ignores unknown fields gracefully).
  Future<Job> convert({
    required String profileId,
    required String pdfPath,
    String? paperStyle,
    String? inkColor,
    double? jitter,
    void Function(double progress)? onProgress,
  }) async {
    final form = FormData();
    form.fields.add(MapEntry('profile_id', profileId));
    if (paperStyle != null) form.fields.add(MapEntry('paper_style', paperStyle));
    if (inkColor != null) form.fields.add(MapEntry('ink_color', inkColor));
    if (jitter != null) form.fields.add(MapEntry('jitter', jitter.toString()));
    form.files.add(MapEntry(
      'pdf',
      await MultipartFile.fromFile(pdfPath, filename: pdfPath.split('/').last),
    ));
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/convert',
        data: form,
        onSendProgress: (sent, total) {
          if (total > 0 && onProgress != null) {
            onProgress(sent / total);
          }
        },
      );
      return Job.fromJson(response.data!);
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  /// GET /jobs/{id} — poll job status.
  Future<Job> getJob(String jobId) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>('/jobs/$jobId');
      return Job.fromJson(response.data!);
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  /// GET /download/{id} — download the finished PDF to [savePath].
  ///
  /// [onProgress] reports download progress as a fraction 0.0–1.0.
  Future<void> downloadResult({
    required String jobId,
    required String savePath,
    void Function(double progress)? onProgress,
  }) async {
    try {
      await _dio.download(
        '/download/$jobId',
        savePath,
        onReceiveProgress: (received, total) {
          if (total > 0 && onProgress != null) {
            onProgress(received / total);
          }
        },
      );
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  // ── Health ──────────────────────────────────────────────────────────────────

  /// GET /health — liveness check (no API key required).
  Future<bool> healthCheck() async {
    try {
      // Temporarily remove the API key header for health
      final response = await _dio.get<Map<String, dynamic>>(
        '/health',
        options: Options(headers: {'X-API-Key': null}),
      );
      return response.data?['status'] == 'ok';
    } on DioException {
      return false;
    }
  }

  // ── Internal ──────────────────────────────────────────────────────────────────

  ApiException _wrap(DioException e) => ApiException.fromDioException(e);
}
