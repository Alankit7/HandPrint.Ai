/// Domain-level API exception surfaced to the UI layer.
library;

import 'package:dio/dio.dart';

class ApiException implements Exception {
  const ApiException({
    required this.message,
    this.statusCode,
    this.detail,
  });

  final String message;
  final int? statusCode;
  final String? detail;

  factory ApiException.fromDioException(DioException e) {
    if (e.response != null) {
      final data = e.response!.data;
      final detail = data is Map ? data['detail']?.toString() : null;
      return ApiException(
        message: _messageForStatus(e.response!.statusCode),
        statusCode: e.response!.statusCode,
        detail: detail,
      );
    }
    return switch (e.type) {
      DioExceptionType.connectionTimeout ||
      DioExceptionType.sendTimeout ||
      DioExceptionType.receiveTimeout =>
        const ApiException(message: 'Request timed out. Please try again.'),
      DioExceptionType.connectionError =>
        const ApiException(message: 'Could not reach the server. Check your connection.'),
      _ => ApiException(message: e.message ?? 'An unexpected error occurred.'),
    };
  }

  static String _messageForStatus(int? code) => switch (code) {
        400 => 'Bad request.',
        413 => 'File is too large.',
        415 => 'Unsupported file type.',
        422 => 'Validation error.',
        403 => 'Invalid or expired download link.',
        404 => 'Job not found.',
        409 => 'Job is not ready yet.',
        500 => 'Server error. Please try again later.',
        _ => 'Request failed (HTTP $code).',
      };

  @override
  String toString() => detail != null ? '$message ($detail)' : message;
}
