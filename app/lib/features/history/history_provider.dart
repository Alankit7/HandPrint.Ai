/// History provider — caches completed job metadata in SharedPreferences
/// so users can re-open results offline without re-downloading.
library;

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

class HistoryEntry {
  const HistoryEntry({
    required this.jobId,
    required this.profileName,
    required this.completedAt,
    this.localPath,
    this.pdfFileName,
  });

  final String jobId;
  final String profileName;
  final DateTime completedAt;
  final String? localPath;
  final String? pdfFileName;

  Map<String, dynamic> toJson() => {
        'job_id': jobId,
        'profile_name': profileName,
        'completed_at': completedAt.toIso8601String(),
        'local_path': localPath,
        'pdf_file_name': pdfFileName,
      };

  factory HistoryEntry.fromJson(Map<String, dynamic> json) {
    return HistoryEntry(
      jobId: json['job_id'] as String,
      profileName: json['profile_name'] as String,
      completedAt: DateTime.parse(json['completed_at'] as String),
      localPath: json['local_path'] as String?,
      pdfFileName: json['pdf_file_name'] as String?,
    );
  }
}

class HistoryState {
  const HistoryState({
    this.entries = const [],
    this.isLoading = false,
  });

  final List<HistoryEntry> entries;
  final bool isLoading;

  HistoryState copyWith({
    List<HistoryEntry>? entries,
    bool? isLoading,
  }) {
    return HistoryState(
      entries: entries ?? this.entries,
      isLoading: isLoading ?? this.isLoading,
    );
  }
}

class HistoryNotifier extends StateNotifier<HistoryState> {
  HistoryNotifier() : super(const HistoryState()) {
    _load();
  }

  static const _key = 'history_entries';

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList(_key) ?? [];
    final entries = raw
        .map((s) => HistoryEntry.fromJson(jsonDecode(s) as Map<String, dynamic>))
        .toList();
    // Sort newest first
    entries.sort((a, b) => b.completedAt.compareTo(a.completedAt));
    state = state.copyWith(entries: entries, isLoading: false);
  }

  /// Add a completed job to history.
  Future<void> add(HistoryEntry entry) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList(_key) ?? [];
    // Avoid duplicates by jobId
    final existing = raw
        .map((s) => HistoryEntry.fromJson(jsonDecode(s) as Map<String, dynamic>))
        .where((e) => e.jobId != entry.jobId)
        .toList();
    existing.add(entry);
    existing.sort((a, b) => b.completedAt.compareTo(a.completedAt));
    final encoded = existing.map((e) => jsonEncode(e.toJson())).toList();
    await prefs.setStringList(_key, encoded);
    state = state.copyWith(entries: existing);
  }

  /// Remove a job from history.
  Future<void> remove(String jobId) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList(_key) ?? [];
    final remaining = raw
        .map((s) => HistoryEntry.fromJson(jsonDecode(s) as Map<String, dynamic>))
        .where((e) => e.jobId != jobId)
        .toList();
    final encoded = remaining.map((e) => jsonEncode(e.toJson())).toList();
    await prefs.setStringList(_key, encoded);
    state = state.copyWith(entries: remaining);
  }

  /// Clear all history.
  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
    state = const HistoryState();
  }
}

final historyProvider =
    StateNotifierProvider<HistoryNotifier, HistoryState>(
  (ref) => HistoryNotifier(),
);
