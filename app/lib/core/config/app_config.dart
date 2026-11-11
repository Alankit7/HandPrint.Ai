/// Default configuration loaded from .env at startup.
/// Overridden at runtime by user-configurable Settings (SharedPreferences).
library;

import 'package:flutter_dotenv/flutter_dotenv.dart';

class AppConfig {
  AppConfig._();

  /// Call once inside main() before runApp.
  static Future<void> load() => dotenv.load(fileName: '.env');

  static String get defaultApiBaseUrl =>
      dotenv.env['API_BASE_URL'] ?? 'http://localhost:8000';

  static String get defaultApiKey =>
      dotenv.env['API_KEY'] ?? 'changeme-generate-a-real-key';

  static int get pollIntervalSeconds =>
      int.tryParse(dotenv.env['POLL_INTERVAL_SECONDS'] ?? '2') ?? 2;
}
