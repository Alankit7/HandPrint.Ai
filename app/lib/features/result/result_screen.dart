/// Result screen — download, preview, share the handwritten PDF.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gap/gap.dart';
import 'package:go_router/go_router.dart';
import 'package:percent_indicator/linear_percent_indicator.dart';
import 'package:syncfusion_flutter_pdfviewer/pdfviewer.dart';

import '../../shared/widgets/error_state.dart';
import '../../shared/widgets/loading_indicator.dart';
import 'result_provider.dart';

class ResultScreen extends ConsumerStatefulWidget {
  const ResultScreen({required this.jobId, super.key});

  final String jobId;

  @override
  ConsumerState<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends ConsumerState<ResultScreen> {
  @override
  void initState() {
    super.initState();
    // Kick off the download on first build
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(resultProvider(widget.jobId).notifier).download(widget.jobId);
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(resultProvider(widget.jobId));
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Handwritten PDF'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/convert'),
        ),
        actions: [
          if (state.hasFile)
            IconButton(
              icon: const Icon(Icons.share_outlined),
              tooltip: 'Share',
              onPressed: () => ref.read(resultProvider(widget.jobId).notifier).share(),
            ),
        ],
      ),
      body: _buildBody(context, state, theme),
    );
  }

  Widget _buildBody(BuildContext context, ResultState state, ThemeData theme) {
    if (state.isDownloading) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.download_outlined, size: 56, color: theme.colorScheme.primary),
              const Gap(16),
              Text('Downloading your PDF…', style: theme.textTheme.titleMedium),
              const Gap(16),
              LinearPercentIndicator(
                lineHeight: 10,
                percent: state.downloadProgress.clamp(0.0, 1.0),
                progressColor: theme.colorScheme.primary,
                backgroundColor: theme.colorScheme.primaryContainer,
                barRadius: const Radius.circular(8),
                animation: true,
                animateFromLastPercent: true,
              ),
              const Gap(8),
              Text('${(state.downloadProgress * 100).toInt()}%',
                  style: theme.textTheme.labelMedium),
            ],
          ),
        ),
      );
    }

    if (state.error != null) {
      return ErrorState(
        message: state.error!,
        onRetry: () => ref.read(resultProvider(widget.jobId).notifier).download(widget.jobId),
      );
    }

    if (state.hasFile) {
      return Column(
        children: [
          Expanded(
            child: SfPdfViewer.file(
              File(state.localPath!),
              key: ValueKey(state.localPath),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => context.go('/convert'),
                    icon: const Icon(Icons.add),
                    label: const Text('New conversion'),
                  ),
                ),
                const Gap(12),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: () =>
                        ref.read(resultProvider(widget.jobId).notifier).share(),
                    icon: const Icon(Icons.share_outlined),
                    label: const Text('Share'),
                  ),
                ),
              ],
            ),
          ),
        ],
      );
    }

    return const LoadingIndicator(message: 'Preparing download…');
  }
}
