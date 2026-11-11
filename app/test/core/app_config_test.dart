/// Tests for AppConfig defaults and type coercions.
library;

import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:handprint_ai/core/config/app_config.dart';

void main() {
  setUp(() {
    // Seed dotenv in-memory without touching the filesystem
    dotenv.testLoad(mergeWith: {
      'API_BASE_URL': 'http://test.example.com',
      'API_VERSION': 'v1',
      'POLL_INTERVAL_MS': '3000',
      'MAX_PDF_SIZE_MB': '25',
    });
  });

  test('reads API_BASE_URL', () {
    expect(AppConfig.apiBaseUrl, 'http://test.example.com');
  });

  test('reads API_VERSION', () {
    expect(AppConfig.apiVersion, 'v1');
  });

  test('parses POLL_INTERVAL_MS', () {
    expect(AppConfig.pollInterval, const Duration(milliseconds: 3000));
  });

  test('parses MAX_PDF_SIZE_MB and derives bytes', () {
    expect(AppConfig.maxPdfSizeMb, 25);
    expect(AppConfig.maxPdfSizeBytes, 25 * 1024 * 1024);
  });

  test('falls back to defaults when keys are absent', () {
    dotenv.testLoad(mergeWith: {});
    expect(AppConfig.apiBaseUrl, 'http://localhost:8000');
    expect(AppConfig.apiVersion, 'v1');
    expect(AppConfig.pollInterval, const Duration(milliseconds: 2000));
    expect(AppConfig.maxPdfSizeMb, 50);
  });
}
