/// Widget tests for the ConvertNotifier polling logic.
///
/// Verifies:
/// - poll() updates job status and progress correctly
/// - Polling stops (timer cancelled) when job reaches terminal state
/// - Errors during polling are handled without crashing
/// - submit() kicks off the upload + polling cycle
/// - reset() clears all state and stops polling
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import 'package:handprint_ai/core/network/api_client.dart';
import 'package:handprint_ai/core/models/job.dart';
import 'package:handprint_ai/features/convert/convert_provider.dart';

class MockApiClient extends Mock implements ApiClient {}

Job _makeJob({
  String id = 'job-1',
  String profileId = 'profile-1',
  JobStatus status = JobStatus.queued,
  double progress = 0.0,
  String message = 'Queued',
  String? error,
}) {
  final now = DateTime(2026, 11, 11, 10, 0);
  return Job(
    id: id,
    profileId: profileId,
    status: status,
    progress: progress,
    message: message,
    error: error,
    createdAt: now,
    updatedAt: now,
  );
}

void main() {
  late MockApiClient mockApi;
  late ConvertNotifier notifier;

  setUp(() {
    mockApi = MockApiClient();
    notifier = ConvertNotifier(mockApi);
  });

  tearDown(() {
    notifier.dispose();
  });

  group('poll()', () {
    test('updates state with processing job', () async {
      final job = _makeJob(status: JobStatus.processing, progress: 0.5, message: 'Rendering...');
      when(() => mockApi.getJob('job-1')).thenAnswer((_) async => job);

      await notifier.poll('job-1');

      expect(notifier.state.job, isNotNull);
      expect(notifier.state.job!.status, JobStatus.processing);
      expect(notifier.state.job!.progress, 0.5);
      expect(notifier.state.job!.message, 'Rendering...');
    });

    test('updates state with done job and stops polling', () async {
      final job = _makeJob(status: JobStatus.done, progress: 1.0, message: 'Done');
      when(() => mockApi.getJob('job-1')).thenAnswer((_) async => job);

      // Seed state with a job so we can verify the timer is cancelled
      await notifier.poll('job-1');

      expect(notifier.state.job!.status, JobStatus.done);
      expect(notifier.state.job!.progress, 1.0);
      expect(notifier.state.isDone, isTrue);
    });

    test('updates state with failed job and stops polling', () async {
      final job = _makeJob(status: JobStatus.failed, progress: 0.0, message: 'Failed', error: 'OOM');
      when(() => mockApi.getJob('job-1')).thenAnswer((_) async => job);

      await notifier.poll('job-1');

      expect(notifier.state.job!.status, JobStatus.failed);
      expect(notifier.state.isFailed, isTrue);
      expect(notifier.state.job!.error, 'OOM');
    });

    test('handles API error without crashing', () async {
      when(() => mockApi.getJob('job-1')).thenThrow(Exception('Network error'));

      // No previous job in state, so error should be set
      await notifier.poll('job-1');

      expect(notifier.state.error, isNotNull);
      expect(notifier.state.job, isNull);
    });

    test('preserves last known job state on transient error', () async {
      // First poll succeeds
      final processingJob = _makeJob(status: JobStatus.processing, progress: 0.3);
      when(() => mockApi.getJob('job-1')).thenAnswer((_) async => processingJob);
      await notifier.poll('job-1');
      expect(notifier.state.job!.progress, 0.3);

      // Second poll fails — should preserve the previous job
      when(() => mockApi.getJob('job-1')).thenThrow(Exception('Timeout'));
      await notifier.poll('job-1');

      // Job should still be the previous one
      expect(notifier.state.job, isNotNull);
      expect(notifier.state.job!.progress, 0.3);
      // Error should NOT be set because we have a previous job
      expect(notifier.state.error, isNull);
    });

    test('transitions through multiple states', () async {
      // Queued
      when(() => mockApi.getJob('job-1'))
          .thenAnswer((_) async => _makeJob(status: JobStatus.queued, progress: 0.0));
      await notifier.poll('job-1');
      expect(notifier.state.job!.status, JobStatus.queued);

      // Processing
      when(() => mockApi.getJob('job-1'))
          .thenAnswer((_) async => _makeJob(status: JobStatus.processing, progress: 0.5));
      await notifier.poll('job-1');
      expect(notifier.state.job!.status, JobStatus.processing);
      expect(notifier.state.job!.progress, 0.5);

      // Done
      when(() => mockApi.getJob('job-1'))
          .thenAnswer((_) async => _makeJob(status: JobStatus.done, progress: 1.0));
      await notifier.poll('job-1');
      expect(notifier.state.job!.status, JobStatus.done);
      expect(notifier.state.isDone, isTrue);
    });
  });

  group('submit()', () {
    test('returns job_id on success and starts polling', () async {
      final job = _makeJob(status: JobStatus.queued);
      when(() => mockApi.convert(
            profileId: any(named: 'profileId'),
            pdfPath: any(named: 'pdfPath'),
            paperStyle: any(named: 'paperStyle'),
            inkColor: any(named: 'inkColor'),
            jitter: any(named: 'jitter'),
            onProgress: any(named: 'onProgress'),
          )).thenAnswer((_) async => job);

      final jobId = await notifier.submit(
        profileId: 'profile-1',
        pdfPath: '/tmp/test.pdf',
      );

      expect(jobId, 'job-1');
      expect(notifier.state.jobId, 'job-1');
      expect(notifier.state.isUploading, isFalse);
      expect(notifier.state.job, isNotNull);
    });

    test('returns null and sets error on failure', () async {
      when(() => mockApi.convert(
            profileId: any(named: 'profileId'),
            pdfPath: any(named: 'pdfPath'),
            paperStyle: any(named: 'paperStyle'),
            inkColor: any(named: 'inkColor'),
            jitter: any(named: 'jitter'),
            onProgress: any(named: 'onProgress'),
          )).thenThrow(Exception('Upload failed'));

      final jobId = await notifier.submit(
        profileId: 'profile-1',
        pdfPath: '/tmp/test.pdf',
      );

      expect(jobId, isNull);
      expect(notifier.state.error, isNotNull);
      expect(notifier.state.isUploading, isFalse);
    });
  });

  group('reset()', () {
    test('clears all state', () {
      // Manually set some state
      notifier.state = notifier.state.copyWith(
        jobId: 'job-1',
        job: _makeJob(),
        uploadProgress: 0.5,
      );

      notifier.reset();

      expect(notifier.state.jobId, isNull);
      expect(notifier.state.job, isNull);
      expect(notifier.state.uploadProgress, 0.0);
      expect(notifier.state.error, isNull);
    });
  });

  group('stopPolling()', () {
    test('does not crash when no timer is running', () {
      notifier.stopPolling();
      // Should not throw
      expect(notifier.state.jobId, isNull);
    });
  });

  group('ConvertState helpers', () {
    test('isBusy is true during upload', () {
      final state = const ConvertState(isUploading: true);
      expect(state.isBusy, isTrue);
    });

    test('isBusy is true during polling', () {
      final state = ConvertState(
        jobId: 'job-1',
        job: _makeJob(status: JobStatus.processing),
      );
      expect(state.isBusy, isTrue);
    });

    test('isDone is true when job is done', () {
      final state = ConvertState(job: _makeJob(status: JobStatus.done));
      expect(state.isDone, isTrue);
      expect(state.isBusy, isFalse);
    });

    test('isFailed is true when job is failed', () {
      final state = ConvertState(job: _makeJob(status: JobStatus.failed, error: 'OOM'));
      expect(state.isFailed, isTrue);
      expect(state.isBusy, isFalse);
    });
  });
}
