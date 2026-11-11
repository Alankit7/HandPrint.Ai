/// Settings provider — persists API base URL and API key in SharedPreferences.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/config/app_config.dart';
import '../../core/network/api_client.dart';

class SettingsState {
  const SettingsState({
    this.apiBaseUrl = '',
    this.apiKey = '',
    this.isLoaded = false,
  });

  final String apiBaseUrl;
  final String apiKey;
  final bool isLoaded;

  SettingsState copyWith({String? apiBaseUrl, String? apiKey, bool? isLoaded}) {
    return SettingsState(
      apiBaseUrl: apiBaseUrl ?? this.apiBaseUrl,
      apiKey: apiKey ?? this.apiKey,
      isLoaded: isLoaded ?? this.isLoaded,
    );
  }
}

class SettingsNotifier extends StateNotifier<SettingsState> {
  SettingsNotifier() : super(const SettingsState()) {
    _load();
  }

  static const _keyBaseUrl = 'api_base_url';
  static const _keyApiKey = 'api_key';

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    state = SettingsState(
      apiBaseUrl: prefs.getString(_keyBaseUrl) ?? AppConfig.defaultApiBaseUrl,
      apiKey: prefs.getString(_keyApiKey) ?? AppConfig.defaultApiKey,
      isLoaded: true,
    );
  }

  Future<void> save({required String baseUrl, required String apiKey}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyBaseUrl, baseUrl);
    await prefs.setString(_keyApiKey, apiKey);
    state = state.copyWith(apiBaseUrl: baseUrl, apiKey: apiKey, isLoaded: true);
  }

  Future<void> reset() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyBaseUrl);
    await prefs.remove(_keyApiKey);
    state = SettingsState(
      apiBaseUrl: AppConfig.defaultApiBaseUrl,
      apiKey: AppConfig.defaultApiKey,
      isLoaded: true,
    );
  }
}

final settingsProvider =
    StateNotifierProvider<SettingsNotifier, SettingsState>(
  (ref) => SettingsNotifier(),
);

/// Convenience provider: yields the ApiClient configured with current settings.
/// Automatically recreated when settings change.
final settingsApiClientProvider = Provider<ApiClient>((ref) {
  final s = ref.watch(settingsProvider);
  return ApiClient(baseUrl: s.apiBaseUrl, apiKey: s.apiKey);
});
