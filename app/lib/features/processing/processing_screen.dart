/// Processing screen — polls backend and shows progress, then navigates to result.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gap/gap.dart';
import 'package:go_router/go_router.dart';
import 'package:percent_indicator/percent_indicator.dart';

import '../../core/models/job_status.dart';
import '../../shared/widgets/error_banner.dart';
import 'processing_provider.dart';

class ProcessingScreen extends ConsumerWidget {
  const ProcessingScreen({required this.jobId, super.key});

  final String jobId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(processingProvider(jobId));
    final colorScheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    // Navigate when done
    ref.listen<ProcessingState>(processingProvider(jobId), (_, next) {
      if (next.isDone && next.downloadToken != null) {
        context.go('/result/$jobId/${Uri.encodeComponent(next.downloadToken!)}');
      }
    });

    return Scaffold(
      appBar: AppBar(
        title: const Text('Generating…'),
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // ── Animated ink icon ────────────────────────────────────────
              const _InkAnimation(),
              const Gap(40),

              // ── Progress ring ─────────────────────────────────────────────
              Center(
                child: CircularPercentIndicator(
                  radius: 80,
                  lineWidth: 10,
                  percent: state.progress.clamp(0.0, 1.0),
                  center: Text(
                    '${(state.progress * 100).toInt()}%',
                    style: textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: colorScheme.primary,
                    ),
                  ),
                  progressColor: colorScheme.primary,
                  backgroundColor: colorScheme.primaryContainer,
                  circularStrokeCap: CircularStrokeCap.round,
                  animation: true,
                  animateFromLastPercent: true,
                ),
              ),
              const Gap(32),

              // ── Status message ───────────────────────────────────────────
              Text(
                state.message,
                textAlign: TextAlign.center,
                style: textTheme.bodyLarge?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                ),
              ),
              const Gap(8),
              Text(
                'Job ID: $jobId',
                textAlign: TextAlign.center,
                style: textTheme.labelSmall?.copyWith(
                  color: colorScheme.outline,
                  fontFamily: 'monospace',
                ),
              ),
              const Gap(32),

              // ── Error ────────────────────────────────────────────────────
              if (state.isFailed)
                Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    ErrorBanner(
                      message: state.error ?? 'Generation failed. Please try again.',
                    ),
                    const Gap(16),
                    FilledButton.icon(
                      onPressed: () => context.go('/'),
                      icon: const Icon(Icons.arrow_back),
                      label: const Text('Try Again'),
                    ),
                  ],
                ),

              // ── Status label ─────────────────────────────────────────────
              if (!state.isFailed)
                _StatusChip(status: state.status),
            ],
          ),
        ),
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});

  final JobStatus status;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final (label, color) = switch (status) {
      JobStatus.pending => ('Queued', colorScheme.secondary),
      JobStatus.processing => ('Processing', colorScheme.primary),
      JobStatus.done => ('Done', Colors.green),
      JobStatus.failed => ('Failed', colorScheme.error),
    };
    return Center(
      child: Chip(
        label: Text(label),
        backgroundColor: color.withOpacity(0.15),
        labelStyle: TextStyle(color: color, fontWeight: FontWeight.w600),
        avatar: status == JobStatus.processing
            ? SizedBox.square(
                dimension: 16,
                child: CircularProgressIndicator(strokeWidth: 2, color: color),
              )
            : null,
      ),
    );
  }
}

class _InkAnimation extends StatefulWidget {
  const _InkAnimation();

  @override
  State<_InkAnimation> createState() => _InkAnimationState();
}

class _InkAnimationState extends State<_InkAnimation>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _scale;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);
    _scale = Tween<double>(begin: 0.9, end: 1.1).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return ScaleTransition(
      scale: _scale,
      child: Icon(
        Icons.draw_outlined,
        size: 72,
        color: colorScheme.primary,
      ),
    );
  }
}
