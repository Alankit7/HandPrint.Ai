/// Widget tests for the ProfilesNotifier polling logic.
///
/// Verifies:
/// - pollTraining() updates profile status and train progress
/// - Polling stops when profile reaches ready/failed state
/// - Errors during polling are silently retried (no state corruption)
/// - startTraining() begins the polling cycle
/// - stopTrainingPoll() cancels the timer
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import 'package:handprint_ai/core/network/api_client.dart';
import 'package:handprint_ai/core/models/profile.dart';
import 'package:handprint_ai/features/profiles/profiles_provider.dart';

class MockApiClient extends Mock implements ApiClient {}

Profile _makeProfile({
  String id = 'profile-1',
  String name = 'Test Writer',
  ProfileStatus status = ProfileStatus.pending,
  int sampleCount = 5,
  double trainProgress = 0.0,
  String? error,
}) {
  final now = DateTime(2026, 11, 11, 10, 0);
  return Profile(
    id: id,
    name: name,
    status: status,
    sampleCount: sampleCount,
    trainProgress: trainProgress,
    error: error,
    createdAt: now,
    updatedAt: now,
  );
}

void main() {
  late MockApiClient mockApi;
  late ProfilesNotifier notifier;

  setUp(() {
    mockApi = MockApiClient();
    notifier = ProfilesNotifier(mockApi);
  });

  tearDown(() {
    notifier.dispose();
  });

  group('pollTraining()', () {
    test('updates profile status to training with progress', () async {
      // Seed a profile in the list
      final initial = _makeProfile(status: ProfileStatus.pending);
      notifier.state = notifier.state.copyWith(
        profiles: [initial],
        trainingProfileId: 'profile-1',
      );

      final training = _makeProfile(status: ProfileStatus.training, trainProgress: 0.4);
      when(() => mockApi.getProfile('profile-1')).thenAnswer((_) async => training);

      await notifier.pollTraining('profile-1');

      expect(notifier.state.profiles, isNotEmpty);
      expect(notifier.state.profiles.first.status, ProfileStatus.training);
      expect(notifier.state.profiles.first.trainProgress, 0.4);
      // Training should still be active
      expect(notifier.state.trainingProfileId, 'profile-1');
    });

    test('stops polling when profile reaches ready', () async {
      notifier.state = notifier.state.copyWith(
        profiles: [_makeProfile(status: ProfileStatus.training, trainProgress: 0.8)],
        trainingProfileId: 'profile-1',
      );

      final ready = _makeProfile(status: ProfileStatus.ready, trainProgress: 1.0);
      when(() => mockApi.getProfile('profile-1')).thenAnswer((_) async => ready);

      await notifier.pollTraining('profile-1');

      expect(notifier.state.profiles.first.status, ProfileStatus.ready);
      expect(notifier.state.profiles.first.trainProgress, 1.0);
      // trainingProfileId should be cleared (timer cancelled)
      expect(notifier.state.trainingProfileId, isNull);
    });

    test('stops polling when profile reaches failed', () async {
      notifier.state = notifier.state.copyWith(
        profiles: [_makeProfile(status: ProfileStatus.training)],
        trainingProfileId: 'profile-1',
      );

      final failed = _makeProfile(status: ProfileStatus.failed, error: 'OOM');
      when(() => mockApi.getProfile('profile-1')).thenAnswer((_) async => failed);

      await notifier.pollTraining('profile-1');

      expect(notifier.state.profiles.first.status, ProfileStatus.failed);
      expect(notifier.state.profiles.first.error, 'OOM');
      expect(notifier.state.trainingProfileId, isNull);
    });

    test('handles API error silently without crashing', () async {
      notifier.state = notifier.state.copyWith(
        profiles: [_makeProfile(status: ProfileStatus.training)],
        trainingProfileId: 'profile-1',
      );

      when(() => mockApi.getProfile('profile-1')).thenThrow(Exception('Network error'));

      await notifier.pollTraining('profile-1');

      // Should not crash, profile should remain unchanged
      expect(notifier.state.profiles.first.status, ProfileStatus.training);
      // Training should still be active (will retry on next tick)
      expect(notifier.state.trainingProfileId, 'profile-1');
    });

    test('updates profile in list without affecting other profiles', () async {
      final p1 = _makeProfile(id: 'profile-1', name: 'Alice', status: ProfileStatus.training);
      final p2 = _makeProfile(id: 'profile-2', name: 'Bob', status: ProfileStatus.ready);
      notifier.state = notifier.state.copyWith(
        profiles: [p1, p2],
        trainingProfileId: 'profile-1',
      );

      final updated = _makeProfile(id: 'profile-1', name: 'Alice', status: ProfileStatus.ready, trainProgress: 1.0);
      when(() => mockApi.getProfile('profile-1')).thenAnswer((_) async => updated);

      await notifier.pollTraining('profile-1');

      expect(notifier.state.profiles.length, 2);
      expect(notifier.state.profiles[0].status, ProfileStatus.ready);
      expect(notifier.state.profiles[0].name, 'Alice');
      expect(notifier.state.profiles[1].status, ProfileStatus.ready);
      expect(notifier.state.profiles[1].name, 'Bob');
    });

    test('transitions through training to ready', () async {
      notifier.state = notifier.state.copyWith(
        profiles: [_makeProfile(status: ProfileStatus.pending)],
        trainingProfileId: 'profile-1',
      );

      // Training
      when(() => mockApi.getProfile('profile-1'))
          .thenAnswer((_) async => _makeProfile(status: ProfileStatus.training, trainProgress: 0.5));
      await notifier.pollTraining('profile-1');
      expect(notifier.state.profiles.first.status, ProfileStatus.training);
      expect(notifier.state.trainingProfileId, 'profile-1');

      // Ready
      when(() => mockApi.getProfile('profile-1'))
          .thenAnswer((_) async => _makeProfile(status: ProfileStatus.ready, trainProgress: 1.0));
      await notifier.pollTraining('profile-1');
      expect(notifier.state.profiles.first.status, ProfileStatus.ready);
      expect(notifier.state.trainingProfileId, isNull);
    });
  });

  group('startTraining()', () {
    test('calls API and sets trainingProfileId', () async {
      when(() => mockApi.startTraining('profile-1')).thenAnswer((_) async {});

      final result = await notifier.startTraining('profile-1');

      expect(result, isTrue);
      expect(notifier.state.trainingProfileId, 'profile-1');
      verify(() => mockApi.startTraining('profile-1')).called(1);
    });

    test('sets error when API fails', () async {
      when(() => mockApi.startTraining('profile-1')).thenThrow(Exception('Server error'));

      final result = await notifier.startTraining('profile-1');

      expect(result, isFalse);
      expect(notifier.state.error, isNotNull);
      expect(notifier.state.trainingProfileId, isNull);
    });
  });

  group('stopTrainingPoll()', () {
    test('clears trainingProfileId', () {
      notifier.state = notifier.state.copyWith(trainingProfileId: 'profile-1');
      notifier.stopTrainingPoll();
      expect(notifier.state.trainingProfileId, isNull);
    });

    test('does not crash when no poll is running', () {
      notifier.stopTrainingPoll();
      expect(notifier.state.trainingProfileId, isNull);
    });
  });

  group('createProfile()', () {
    test('returns profile_id on success and adds to list', () async {
      final profile = _makeProfile(id: 'new-1', name: 'New Writer', status: ProfileStatus.pending);
      when(() => mockApi.createProfile(
            name: any(named: 'name'),
            samplePaths: any(named: 'samplePaths'),
            onProgress: any(named: 'onProgress'),
          )).thenAnswer((_) async => profile);

      final id = await notifier.createProfile(name: 'New Writer', samplePaths: ['/tmp/a.png']);

      expect(id, 'new-1');
      expect(notifier.state.profiles, isNotEmpty);
      expect(notifier.state.profiles.last.name, 'New Writer');
      expect(notifier.state.isUploading, isFalse);
      expect(notifier.state.createdProfileId, 'new-1');
    });

    test('returns null and sets uploadError on failure', () async {
      when(() => mockApi.createProfile(
            name: any(named: 'name'),
            samplePaths: any(named: 'samplePaths'),
            onProgress: any(named: 'onProgress'),
          )).thenThrow(Exception('Upload failed'));

      final id = await notifier.createProfile(name: 'Test', samplePaths: ['/tmp/a.png']);

      expect(id, isNull);
      expect(notifier.state.uploadError, isNotNull);
      expect(notifier.state.isUploading, isFalse);
    });
  });

  group('fetchProfile()', () {
    test('returns profile on success', () async {
      final profile = _makeProfile(id: 'p1', status: ProfileStatus.ready);
      when(() => mockApi.getProfile('p1')).thenAnswer((_) async => profile);

      final result = await notifier.fetchProfile('p1');

      expect(result, isNotNull);
      expect(result!.status, ProfileStatus.ready);
    });

    test('returns null on error', () async {
      when(() => mockApi.getProfile('p1')).thenThrow(Exception('Not found'));

      final result = await notifier.fetchProfile('p1');

      expect(result, isNull);
    });
  });

  group('ProfilesState helpers', () {
    test('clearErrors removes error and uploadError', () {
      notifier.state = notifier.state.copyWith(
        error: 'some error',
        uploadError: 'upload error',
      );
      notifier.clearErrors();
      expect(notifier.state.error, isNull);
      expect(notifier.state.uploadError, isNull);
    });
  });
}
