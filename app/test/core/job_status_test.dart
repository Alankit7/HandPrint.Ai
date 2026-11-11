/// Tests for JobStatusResponse parsing and JobStatus helpers.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:handprint_ai/core/models/job_status.dart';

void main() {
  group('JobStatusX.fromString', () {
    test('parses all valid values', () {
      expect(JobStatusX.fromString('pending'), JobStatus.pending);
      expect(JobStatusX.fromString('processing'), JobStatus.processing);
      expect(JobStatusX.fromString('done'), JobStatus.done);
      expect(JobStatusX.fromString('failed'), JobStatus.failed);
    });

    test('falls back to pending for unknown string', () {
      expect(JobStatusX.fromString('unknown'), JobStatus.pending);
    });
  });

  group('JobStatus helpers', () {
    test('isTerminal is true only for done and failed', () {
      expect(JobStatus.done.isTerminal, isTrue);
      expect(JobStatus.failed.isTerminal, isTrue);
      expect(JobStatus.pending.isTerminal, isFalse);
      expect(JobStatus.processing.isTerminal, isFalse);
    });

    test('isActive is true only for pending and processing', () {
      expect(JobStatus.pending.isActive, isTrue);
      expect(JobStatus.processing.isActive, isTrue);
      expect(JobStatus.done.isActive, isFalse);
      expect(JobStatus.failed.isActive, isFalse);
    });
  });

  group('JobStatusResponse.fromJson', () {
    test('parses a done response with download token', () {
      final json = {
        'job_id': 'abc-123',
        'status': 'done',
        'progress': 1.0,
        'message': 'Done',
        'download_token': 'abc-123.sigtoken',
      };
      final r = JobStatusResponse.fromJson(json);
      expect(r.jobId, 'abc-123');
      expect(r.status, JobStatus.done);
      expect(r.progress, 1.0);
      expect(r.downloadToken, 'abc-123.sigtoken');
    });

    test('parses a processing response without token', () {
      final json = {
        'job_id': 'xyz',
        'status': 'processing',
        'progress': 0.45,
        'message': 'Rendering line 3/8…',
      };
      final r = JobStatusResponse.fromJson(json);
      expect(r.status, JobStatus.processing);
      expect(r.progress, closeTo(0.45, 0.001));
      expect(r.downloadToken, isNull);
    });

    test('handles missing message gracefully', () {
      final json = {
        'job_id': 'x',
        'status': 'pending',
        'progress': 0.0,
      };
      final r = JobStatusResponse.fromJson(json);
      expect(r.message, '');
    });
  });
}
