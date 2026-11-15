/// Profiles provider — list, create (with upload progress), train, and poll.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';
import '../../core/models/profile.dart';
import '../../core/network/api_client.dart';
import '../settings/settings_provider.dart';

// ── State ──────────────────────────────────────────────────────────────────────

class ProfilesState {
  const ProfilesState({
    this.profiles = const [],
    this.isLoading = false,
    this.error,
    this.isUploading = false,
    this.uploadProgress = 0.0,
    this.uploadError,
    this.createdProfileId,
    this.trainingProfileId,
  });

  final List<Profile> profiles;
  final bool isLoading;
  final String? error;
  final bool isUploading;
  final double uploadProgress;
  final String? uploadError;
  final String? createdProfileId;
  final String? trainingProfileId;

  ProfilesState copyWith({
    List<Profile>? profiles,
    bool? isLoading,
    String? error,
    bool? isUploading,
    double? uploadProgress,
    String? uploadError,
    String? createdProfileId,
    String? trainingProfileId,
    bool clearError = false,
    bool clearUploadError = false,
    bool clearCreatedId = false,
  }) {
    return ProfilesState(
      profiles: profiles ?? this.profiles,
      isLoading: isLoading ?? this.isLoading,
      error: clearError ? null : (error ?? this.error),
      isUploading: isUploading ?? this.isUploading,
      uploadProgress: uploadProgress ?? this.uploadProgress,
      uploadError: clearUploadError ? null : (uploadError ?? this.uploadError),
      createdProfileId: clearCreatedId ? null : (createdProfileId ?? this.createdProfileId),
      trainingProfileId: trainingProfileId ?? this.trainingProfileId,
    );
  }
}

// ── Notifier ──────────────────────────────────────────────────────────────────

class ProfilesNotifier extends StateNotifier<ProfilesState> {
  ProfilesNotifier(this._api) : super(const ProfilesState());

  final ApiClient _api;
  Timer? _trainPollTimer;

  /// Create a new profile by uploading sample images.
  Future<String?> createProfile({
    required String name,
    required List<String> samplePaths,
  }) async {
    state = state.copyWith(
      isUploading: true,
      uploadProgress: 0.0,
      clearUploadError: true,
      clearCreatedId: true,
    );
    try {
      final profile = await _api.createProfile(
        name: name,
        samplePaths: samplePaths,
        onProgress: (p) {
          state = state.copyWith(uploadProgress: p);
        },
      );
      state = state.copyWith(
        isUploading: false,
        uploadProgress: 1.0,
        createdProfileId: profile.id,
        profiles: [...state.profiles, profile],
      );
      return profile.id;
    } catch (e) {
      state = state.copyWith(
        isUploading: false,
        uploadError: e.toString(),
      );
      return null;
    }
  }

  /// Start training for a profile and begin polling its status.
  Future<bool> startTraining(String profileId) async {
    try {
      await _api.startTraining(profileId);
      state = state.copyWith(trainingProfileId: profileId);
      _startTrainPolling(profileId);
      return true;
    } catch (e) {
      state = state.copyWith(error: e.toString());
      return false;
    }
  }

  /// Poll a single profile's status (used internally by the timer).
  Future<void> pollTraining(String profileId) async {
    try {
      final profile = await _api.getProfile(profileId);
      final updated = state.profiles.map((p) {
        return p.id == profileId ? profile : p;
      }).toList();
      state = state.copyWith(profiles: updated);

      if (profile.status.isTerminal) {
        _trainPollTimer?.cancel();
        _trainPollTimer = null;
        state = state.copyWith(trainingProfileId: null);
      }
    } catch (_) {
      // Transient errors are silently retried on next tick.
    }
  }

  void _startTrainPolling(String profileId) {
    _trainPollTimer?.cancel();
    _trainPollTimer = Timer.periodic(
      Duration(seconds: AppConfig.pollIntervalSeconds),
      (_) => pollTraining(profileId),
    );
    pollTraining(profileId);
  }

  void stopTrainingPoll() {
    _trainPollTimer?.cancel();
    _trainPollTimer = null;
    state = state.copyWith(trainingProfileId: null);
  }

  /// Fetch a single profile by ID (one-shot, no polling).
  Future<Profile?> fetchProfile(String profileId) async {
    try {
      return await _api.getProfile(profileId);
    } catch (_) {
      return null;
    }
  }

  void clearErrors() {
    state = state.copyWith(clearError: true, clearUploadError: true);
  }

  /// For tests only — directly seeds state without going through the API.
  @visibleForTesting
  void seedState(ProfilesState s) => state = s;

  @override
  void dispose() {
    _trainPollTimer?.cancel();
    super.dispose();
  }
}

// ── Provider ──────────────────────────────────────────────────────────────────

final profilesProvider =
    StateNotifierProvider.autoDispose<ProfilesNotifier, ProfilesState>(
  (ref) {
    final api = ref.watch(settingsApiClientProvider);
    return ProfilesNotifier(api);
  },
);
