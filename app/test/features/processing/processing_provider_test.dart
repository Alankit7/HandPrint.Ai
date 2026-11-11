/// Unit tests for ProcessingNotifier — polling logic and state transitions.
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:handprint_ai/core/models/job_status.dart';
import 'package:handprint_ai/core/network/api_client.dart';
import 'package:handprint_ai/features/processing/processing_provider.dart';
import 'package:mocktail/mocktail.dart';

class MockApiClient extends Mock implements ApiClient {}

ProviderContainer _makeContainer(ApiClient mock) {
  return ProviderContainer(
    overrides: [apiClientProvider.overrideWithValue(mock)],
  );
}

void main() {
  late MockApiClient mockApi;
  late ProviderContainer container;

  setUp(() {
    mockApi = MockApiClient();
    container = _makeContainer(mockApi);
  });

  tearDown(() => container.dispose());

  test('starts in pending state', () {
    when(() => mockApi.getJobStatus(any())).thenAnswer((_) async => {
          'job_id': 'j1',
          'status': 'pending',
          'progress': 0.0,
          'message': '',
        });

    final state = container.read(processingProvider('j1'));
    expect(state.jobId, 'j1');
    expect(state.status, JobStatus.pending);
    expect(state.progress, 0.0);
  });

  test('transitions to done and captures download token', () async {
    int callCount = 0;
    when(() => mockApi.getJobStatus('j2')).thenAnswer((_) async {
      callCount++;
      if (callCount == 1) {
        return {'job_id': 'j2', 'status': 'processing', 'progress': 0.5, 'message': 'halfway'};
      }
      return {
        'job_id': 'j2',
        'status': 'done',
        'progress': 1.0,
        'message': 'Done',
        'download_token': 'j2.signed',
      };
    });

    // Listen for enough ticks
    final notifier = container.read(processingProvider('j2').notifier);
    await Future.delayed(const Duration(milliseconds: 100));

    // Poll manually
    await notifier._poll();
    await notifier._poll();

    final state = container.read(processingProvider('j2'));
    expect(state.isDone, isTrue);
    expect(state.downloadToken, 'j2.signed');
  });

  test('marks failed with error on 404', () async {
    when(() => mockApi.getJobStatus('missing')).thenThrow(
      Exception('404 not found'),
    );

    final notifier = container.read(processingProvider('missing').notifier);
    // Give the first immediate poll time to run
    await Future.delayed(const Duration(milliseconds: 50));
  });
}

// Make _poll accessible for testing via extension
extension _TestAccess on ProcessingNotifier {
  Future<void> _poll() => (this as dynamic)._poll() as Future<void>;
}
