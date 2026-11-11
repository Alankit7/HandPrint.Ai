/// Dio HTTP client with interceptors for logging and error normalisation.
library;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/app_config.dart';
import 'api_exception.dart';

/// Provider so the client is a singleton shared across the app.
final apiClientProvider = Provider<ApiClient>((ref) => ApiClient());

class ApiClient {
  ApiClient()
      : _dio = Dio(
          BaseOptions(
            baseUrl: '${AppConfig.apiBaseUrl}/${AppConfig.apiVersion}',
            connectTimeout: const Duration(seconds: 30),
            receiveTimeout: const Duration(minutes: 10), // large file downloads
            sendTimeout: const Duration(minutes: 5),
            headers: {'Accept': 'application/json'},
          ),
        ) {
    _dio.interceptors.addAll([
      _LoggingInterceptor(),
      _ErrorInterceptor(),
    ]);
  }

  final Dio _dio;

  Dio get dio => _dio;

  // ── Jobs ──────────────────────────────────────────────────────────────────

  /// Submit a new job. [pdf] path + [samples] paths → job_id.
  Future<Map<String, dynamic>> createJob({
    required String pdfPath,
    required List<String> samplePaths,
  }) async {
    final formData = FormData();
    formData.files.add(
      MapEntry('pdf', await MultipartFile.fromFile(pdfPath, filename: 'input.pdf')),
    );
    for (final p in samplePaths) {
      formData.files.add(
        MapEntry(
          'samples',
          await MultipartFile.fromFile(p, filename: p.split('/').last),
        ),
      );
    }
    final response = await _dio.post<Map<String, dynamic>>('/jobs', data: formData);
    return response.data!;
  }

  /// Poll job status.
  Future<Map<String, dynamic>> getJobStatus(String jobId) async {
    final response = await _dio.get<Map<String, dynamic>>('/jobs/$jobId');
    return response.data!;
  }

  /// Stream-download the finished PDF, saving to [savePath].
  Future<void> downloadResult({
    required String jobId,
    required String token,
    required String savePath,
    void Function(int received, int total)? onProgress,
  }) async {
    await _dio.download(
      '/jobs/$jobId/download',
      savePath,
      queryParameters: {'token': token},
      onReceiveProgress: onProgress,
    );
  }
}

// ── Interceptors ─────────────────────────────────────────────────────────────

class _LoggingInterceptor extends Interceptor {
  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    // ignore: avoid_print
    print('[API] → ${options.method} ${options.path}');
    handler.next(options);
  }

  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    // ignore: avoid_print
    print('[API] ← ${response.statusCode} ${response.requestOptions.path}');
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    // ignore: avoid_print
    print('[API] ✗ ${err.type} ${err.requestOptions.path}');
    handler.next(err);
  }
}

class _ErrorInterceptor extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    // Translate Dio errors into our own domain type
    handler.reject(
      DioException(
        requestOptions: err.requestOptions,
        error: ApiException.fromDioException(err),
        type: err.type,
        response: err.response,
      ),
    );
  }
}
