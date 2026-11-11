/// Central configuration sourced from .env at startup.
///
/// All tunables are here — no magic strings scattered through the codebase.
library;

import 'package:flutter_dotenv/flutter_dotenv.dart';

class AppConfig {
  AppConfig._();

  /// Call once inside `main()` before `runApp`.
  static Future<void> load() => dotenv.load(fileName: '.env');

  static String get apiBaseUrl =>
      dotenv.env['API_BASE_URL'] ?? 'http://localhost:8000';

  static String get apiVersion => dotenv.env['API_VERSION'] ?? 'v1';

  static Duration get pollInterval => Duration(
        milliseconds:
            int.tryParse(dotenv.env['POLL_INTERVAL_MS'] ?? '2000') ?? 2000,
      );

  static int get maxPdfSizeMb =>
      int.tryParse(dotenv.env['MAX_PDF_SIZE_MB'] ?? '50') ?? 50;

  static int get maxPdfSizeBytes => maxPdfSizeMb * 1024 * 1024;
}
