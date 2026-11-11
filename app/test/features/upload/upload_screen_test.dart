/// Widget tests for UploadScreen — verifies key UI elements and interactions.
library;

import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:handprint_ai/core/network/api_client.dart';
import 'package:handprint_ai/features/upload/upload_provider.dart';
import 'package:handprint_ai/features/upload/upload_screen.dart';
import 'package:handprint_ai/shared/theme/app_theme.dart';
import 'package:mocktail/mocktail.dart';

class MockApiClient extends Mock implements ApiClient {}

Widget _buildTestApp({required Widget home, List<Override> overrides = const []}) {
  final router = GoRouter(routes: [
    GoRoute(path: '/', builder: (_, __) => home),
    GoRoute(path: '/processing/:jobId', builder: (_, s) => Scaffold(body: Text(s.pathParameters['jobId']!))),
  ]);

  return ProviderScope(
    overrides: overrides,
    child: MaterialApp.router(
      theme: AppTheme.light,
      routerConfig: router,
    ),
  );
}

void main() {
  setUpAll(() {
    dotenv.testLoad(mergeWith: {
      'API_BASE_URL': 'http://localhost:8000',
      'API_VERSION': 'v1',
      'POLL_INTERVAL_MS': '2000',
      'MAX_PDF_SIZE_MB': '50',
    });
  });

  testWidgets('shows hero text', (tester) async {
    final mock = MockApiClient();
    await tester.pumpWidget(_buildTestApp(
      home: const UploadScreen(),
      overrides: [apiClientProvider.overrideWithValue(mock)],
    ));
    await tester.pumpAndSettle();
    expect(find.textContaining('your handwriting'), findsOneWidget);
  });

  testWidgets('submit button is disabled with no files', (tester) async {
    final mock = MockApiClient();
    await tester.pumpWidget(_buildTestApp(
      home: const UploadScreen(),
      overrides: [apiClientProvider.overrideWithValue(mock)],
    ));
    await tester.pumpAndSettle();

    final button = find.widgetWithText(FilledButton, 'Generate Handwriting');
    expect(button, findsOneWidget);
    // Disabled buttons don't respond to tap
    final widget = tester.widget<FilledButton>(button);
    expect(widget.onPressed, isNull);
  });

  testWidgets('shows error banner when state has error', (tester) async {
    final mock = MockApiClient();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(mock),
          uploadProvider.overrideWith(
            (ref) => UploadNotifier(ref.watch(apiClientProvider))
              ..state = const UploadState(error: 'Test error message'),
          ),
        ],
        child: MaterialApp(
          theme: AppTheme.light,
          home: const UploadScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Test error message'), findsOneWidget);
  });

  testWidgets('shows "Select PDF" drop zone', (tester) async {
    final mock = MockApiClient();
    await tester.pumpWidget(_buildTestApp(
      home: const UploadScreen(),
      overrides: [apiClientProvider.overrideWithValue(mock)],
    ));
    await tester.pumpAndSettle();
    expect(find.text('Select PDF'), findsOneWidget);
  });

  testWidgets('shows "Select handwriting samples" drop zone', (tester) async {
    final mock = MockApiClient();
    await tester.pumpWidget(_buildTestApp(
      home: const UploadScreen(),
      overrides: [apiClientProvider.overrideWithValue(mock)],
    ));
    await tester.pumpAndSettle();
    expect(find.textContaining('handwriting samples'), findsOneWidget);
  });
}
