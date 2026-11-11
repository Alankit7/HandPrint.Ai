/// Widget tests for ProcessingScreen.
library;

import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:handprint_ai/core/models/job_status.dart';
import 'package:handprint_ai/core/network/api_client.dart';
import 'package:handprint_ai/features/processing/processing_provider.dart';
import 'package:handprint_ai/features/processing/processing_screen.dart';
import 'package:handprint_ai/shared/theme/app_theme.dart';
import 'package:mocktail/mocktail.dart';

class MockApiClient extends Mock implements ApiClient {}

Widget _wrap(
  Widget child, {
  List<Override> overrides = const [],
  String initialPath = '/',
}) {
  final router = GoRouter(
    initialLocation: initialPath,
    routes: [
      GoRoute(path: '/', builder: (_, __) => child),
      GoRoute(path: '/result/:jobId/:token', builder: (_, s) => Scaffold(body: Text('result:${s.pathParameters['jobId']}'))),
      GoRoute(path: '/', builder: (_, __) => const Scaffold(body: Text('home'))),
    ],
  );
  return ProviderScope(
    overrides: overrides,
    child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
  );
}

void main() {
  setUpAll(() {
    dotenv.testLoad(mergeWith: {
      'API_BASE_URL': 'http://localhost:8000',
      'API_VERSION': 'v1',
      'POLL_INTERVAL_MS': '60000', // very long to avoid spurious polls
      'MAX_PDF_SIZE_MB': '50',
    });
  });

  testWidgets('shows Generating title', (tester) async {
    final mock = MockApiClient();
    when(() => mock.getJobStatus(any())).thenAnswer((_) async => {
          'job_id': 'j1', 'status': 'processing', 'progress': 0.3, 'message': 'Working…',
        });

    await tester.pumpWidget(_wrap(
      const ProcessingScreen(jobId: 'j1'),
      overrides: [apiClientProvider.overrideWithValue(mock)],
    ));
    await tester.pump(); // initial frame
    expect(find.text('Generating…'), findsOneWidget);
  });

  testWidgets('shows job ID', (tester) async {
    final mock = MockApiClient();
    when(() => mock.getJobStatus(any())).thenAnswer((_) async => {
          'job_id': 'my-job-id', 'status': 'processing', 'progress': 0.0, 'message': '',
        });

    await tester.pumpWidget(_wrap(
      const ProcessingScreen(jobId: 'my-job-id'),
      overrides: [apiClientProvider.overrideWithValue(mock)],
    ));
    await tester.pump();
    expect(find.textContaining('my-job-id'), findsOneWidget);
  });

  testWidgets('shows error message and retry button on failure', (tester) async {
    final mock = MockApiClient();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(mock),
          processingProvider('fail-job').overrideWith(
            (ref, id) => ProcessingNotifier(ref.watch(apiClientProvider), id)
              ..state = ProcessingState(
                jobId: 'fail-job',
                status: JobStatus.failed,
                error: 'OOM error',
                message: 'Generation failed',
              ),
          ),
        ],
        child: MaterialApp(
          theme: AppTheme.light,
          home: const ProcessingScreen(jobId: 'fail-job'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('OOM error'), findsOneWidget);
    expect(find.text('Try Again'), findsOneWidget);
  });
}
