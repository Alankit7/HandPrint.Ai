/// Result screen — downloads and previews the finished handwritten PDF.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gap/gap.dart';
import 'package:go_router/go_router.dart';
import 'package:percent_indicator/linear_percent_indicator.dart';
import 'package:syncfusion_flutter_pdfviewer/pdfviewer.dart';

import '../../shared/widgets/error_banner.dart';
import 'result_provider.dart';

class ResultScreen extends ConsumerStatefulWidget {
  const ResultScreen({
    required this.jobId,
    required this.downloadToken,
    super.key,
  });

  final String jobId;
  final String downloadToken;

  @override
  ConsumerState<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends ConsumerState<ResultScreen> {
  @override
  void initState() {
    super.initState();
    // Kick off the download as soon as the screen appears
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref
          .read(resultProvider((widget.jobId, widget.downloadToken)).notifier)
          .download();
    });
  }

  @override
  Widget build(BuildContext context) {
    final state =
        ref.watch(resultProvider((widget.jobId, widget.downloadToken)));
    final notifier =
        ref.read(resultProvider((widget.jobId, widget.downloadToken)).notifier);
    final colorScheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Your Handwritten PDF'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          tooltip: 'Back to home',
          onPressed: () => context.go('/'),
        ),
        actions: [
          if (state.hasFile)
            IconButton(
              icon: const Icon(Icons.share_outlined),
              tooltip: 'Share',
              onPressed: () => _share(state.localPath!),
            ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            // ── Error ──────────────────────────────────────────────────────
            if (state.error != null)
              ErrorBanner(
                message: state.error!,
                onDismiss: notifier.clearError,
              ),

            // ── Download progress ──────────────────────────────────────────
            if (state.isDownloading) ...[
              const Gap(32),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 32),
                child: Column(
                  children: [
                    Icon(Icons.download_outlined,
                        size: 56, color: colorScheme.primary),
                    const Gap(16),
                    Text(
                      'Downloading your PDF…',
                      style: textTheme.titleMedium,
                    ),
                    const Gap(16),
                    LinearPercentIndicator(
                      lineHeight: 10,
                      percent: state.downloadProgress.clamp(0.0, 1.0),
                      progressColor: colorScheme.primary,
                      backgroundColor: colorScheme.primaryContainer,
                      barRadius: const Radius.circular(8),
                      animation: true,
                      animateFromLastPercent: true,
                    ),
                    const Gap(8),
                    Text(
                      '${(state.downloadProgress * 100).toInt()}%',
                      style: textTheme.labelMedium?.copyWith(
                        color: colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ],

            // ── PDF viewer ─────────────────────────────────────────────────
            if (state.hasFile)
              Expanded(
                child: SfPdfViewer.file(
                  File(state.localPath!),
                  key: ValueKey(state.localPath),
                ),
              ),

            // ── Action bar ─────────────────────────────────────────────────
            if (state.hasFile || state.error != null)
              _ActionBar(
                hasFile: state.hasFile,
                localPath: state.localPath,
                onRetry: state.error != null ? notifier.download : null,
                onNewJob: () => context.go('/'),
              ),
          ],
        ),
      ),
    );
  }

  void _share(String path) {
    // Share plugin integration point; just show a snackbar for now.
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('File saved at: $path')),
    );
  }
}

class _ActionBar extends StatelessWidget {
  const _ActionBar({
    required this.hasFile,
    required this.localPath,
    required this.onNewJob,
    this.onRetry,
  });

  final bool hasFile;
  final String? localPath;
  final VoidCallback? onRetry;
  final VoidCallback onNewJob;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Expanded(
            child: OutlinedButton.icon(
              onPressed: onNewJob,
              icon: const Icon(Icons.add),
              label: const Text('New job'),
            ),
          ),
          if (onRetry != null) ...[
            const Gap(12),
            Expanded(
              child: FilledButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry download'),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
