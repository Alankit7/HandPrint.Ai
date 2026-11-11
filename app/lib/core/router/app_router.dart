/// go_router configuration — all named routes in one place.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/processing/processing_screen.dart';
import '../../features/result/result_screen.dart';
import '../../features/upload/upload_screen.dart';

// Named route constants (use these instead of raw strings)
abstract class AppRoutes {
  static const upload = '/';
  static const processing = '/processing/:jobId';
  static const result = '/result/:jobId/:token';
}

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: AppRoutes.upload,
    debugLogDiagnostics: false,
    errorBuilder: (context, state) => _ErrorScreen(error: state.error),
    routes: [
      GoRoute(
        path: AppRoutes.upload,
        name: 'upload',
        builder: (context, state) => const UploadScreen(),
      ),
      GoRoute(
        path: AppRoutes.processing,
        name: 'processing',
        builder: (context, state) {
          final jobId = state.pathParameters['jobId']!;
          return ProcessingScreen(jobId: jobId);
        },
      ),
      GoRoute(
        path: AppRoutes.result,
        name: 'result',
        builder: (context, state) {
          final jobId = state.pathParameters['jobId']!;
          final token = Uri.decodeComponent(state.pathParameters['token']!);
          return ResultScreen(jobId: jobId, downloadToken: token);
        },
      ),
    ],
  );
});

class _ErrorScreen extends StatelessWidget {
  const _ErrorScreen({this.error});

  final Exception? error;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Page not found')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 64),
            const SizedBox(height: 16),
            Text(error?.toString() ?? 'Unknown route'),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: () => context.go('/'),
              child: const Text('Go home'),
            ),
          ],
        ),
      ),
    );
  }
}
