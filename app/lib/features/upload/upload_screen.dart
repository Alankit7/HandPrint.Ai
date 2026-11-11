/// Home / upload screen — select PDF + samples, then submit.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gap/gap.dart';
import 'package:go_router/go_router.dart';

import '../../shared/widgets/error_banner.dart';
import '../../shared/widgets/file_drop_zone.dart';
import 'upload_provider.dart';

class UploadScreen extends ConsumerWidget {
  const UploadScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(uploadProvider);
    final notifier = ref.read(uploadProvider.notifier);
    final textTheme = Theme.of(context).textTheme;
    final colorScheme = Theme.of(context).colorScheme;

    // Navigate to processing when job_id is available
    ref.listen<UploadState>(uploadProvider, (_, next) {
      if (next.submittedJobId != null) {
        context.go('/processing/${next.submittedJobId}');
      }
    });

    return Scaffold(
      appBar: AppBar(
        title: const Text('Handprint AI'),
        actions: [
          IconButton(
            icon: const Icon(Icons.info_outline),
            tooltip: 'About',
            onPressed: () => _showAbout(context),
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // ── Hero text ────────────────────────────────────────────────
              Text(
                'Your words,\nyour handwriting.',
                style: textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const Gap(8),
              Text(
                'Upload a printed PDF and a few pages of your handwriting samples. '
                'We'll render the whole document in your style.',
                style: textTheme.bodyLarge?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                ),
              ),
              const Gap(32),

              // ── PDF drop zone ────────────────────────────────────────────
              FileDropZone(
                icon: Icons.picture_as_pdf_outlined,
                label: 'Select PDF',
                hint: 'Tap to pick a printed PDF document',
                onTap: notifier.pickPdf,
                isSelected: state.hasPdf,
                selectedLabel: state.pdfName,
              ),
              const Gap(16),

              // ── Sample images ────────────────────────────────────────────
              FileDropZone(
                icon: Icons.draw_outlined,
                label: 'Select handwriting samples',
                hint: 'Pick 1–8 scanned handwriting images (JPG / PNG)',
                onTap: notifier.pickSamples,
                isSelected: state.hasSamples,
                selectedLabel: '${state.samplePaths.length} sample(s) selected',
              ),

              // Sample chips
              if (state.hasSamples) ...[
                const Gap(8),
                Wrap(
                  spacing: 8,
                  runSpacing: 4,
                  children: List.generate(state.samplePaths.length, (i) {
                    final name = state.samplePaths[i].split('/').last;
                    return Chip(
                      label: Text(name),
                      deleteIcon: const Icon(Icons.close, size: 16),
                      onDeleted: () => notifier.removeSample(i),
                    );
                  }),
                ),
              ],
              const Gap(16),

              // ── Error ────────────────────────────────────────────────────
              if (state.error != null)
                ErrorBanner(
                  message: state.error!,
                  onDismiss: notifier.clearError,
                ),

              const Gap(16),

              // ── Submit button ─────────────────────────────────────────────
              FilledButton.icon(
                onPressed: state.canSubmit ? () => notifier.submit() : null,
                icon: state.isSubmitting
                    ? const SizedBox.square(
                        dimension: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.auto_awesome),
                label: Text(state.isSubmitting ? 'Uploading…' : 'Generate Handwriting'),
              ),

              const Gap(8),

              // ── Reset ──────────────────────────────────────────────────
              if (state.hasPdf || state.hasSamples)
                TextButton.icon(
                  onPressed: notifier.reset,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Start over'),
                ),
            ],
          ),
        ),
      ),
    );
  }

  void _showAbout(BuildContext context) {
    showAboutDialog(
      context: context,
      applicationName: 'Handprint AI',
      applicationVersion: '1.0.0',
      applicationLegalese: '© 2026 Handprint AI',
      children: const [
        SizedBox(height: 16),
        Text(
          'Convert any printed PDF into personalised handwriting using a '
          'few-shot diffusion model running on a GPU server.',
        ),
      ],
    );
  }
}
