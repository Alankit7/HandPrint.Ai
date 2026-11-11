/// Convert screen — pick PDF, choose profile, configure options, submit, poll.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import 'package:gap/gap.dart';
import 'package:go_router/go_router.dart';
import 'package:percent_indicator/percent_indicator.dart';

import '../../core/models/profile.dart';
import '../../shared/widgets/empty_state.dart';
import '../profiles/profiles_provider.dart';
import 'convert_provider.dart';

class ConvertScreen extends ConsumerStatefulWidget {
  const ConvertScreen({super.key});

  @override
  ConsumerState<ConvertScreen> createState() => _ConvertScreenState();
}

class _ConvertScreenState extends ConsumerState<ConvertScreen> {
  String? _selectedProfileId;
  String? _pdfPath;
  String _paperStyle = 'plain';
  Color _inkColor = const Color(0xFF23235A);
  double _jitter = 2.0;

  @override
  Widget build(BuildContext context) {
    final profilesState = ref.watch(profilesProvider);
    final convertState = ref.watch(convertProvider);

    // Navigate to result when job is done
    ref.listen<ConvertState>(convertProvider, (_, next) {
      if (next.isDone && next.jobId != null) {
        context.go('/result/${next.jobId}');
      }
    });

    final readyProfiles = profilesState.profiles
        .where((p) => p.status == ProfileStatus.ready)
        .toList();

    return Scaffold(
      appBar: AppBar(title: const Text('Convert')),
      body: convertState.isBusy
          ? _ProgressView(state: convertState)
          : _buildForm(context, readyProfiles, profilesState),
    );
  }

  Widget _buildForm(
    BuildContext context,
    List<Profile> readyProfiles,
    ProfilesState profilesState,
  ) {
    if (readyProfiles.isEmpty) {
      return const EmptyState(
        icon: Icons.person_off_outlined,
        title: 'No ready profiles',
        message: 'Train a profile first, then come back here to convert a PDF.',
      );
    }

    final theme = Theme.of(context);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // ── Profile dropdown ───────────────────────────────────────────────
          Text('Writer Profile', style: theme.textTheme.titleSmall),
          const Gap(8),
          DropdownButtonFormField<String>(
            value: _selectedProfileId,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.person_outline),
            ),
            hint: const Text('Select a trained profile'),
            items: readyProfiles.map((p) {
              return DropdownMenuItem(value: p.id, child: Text(p.name));
            }).toList(),
            onChanged: (v) => setState(() => _selectedProfileId = v),
          ),
          const Gap(24),

          // ── PDF picker ──────────────────────────────────────────────────────
          Text('Source PDF', style: theme.textTheme.titleSmall),
          const Gap(8),
          OutlinedButton.icon(
            onPressed: _pickPdf,
            icon: const Icon(Icons.picture_as_pdf_outlined),
            label: Text(_pdfPath != null
                ? _pdfPath!.split('/').last
                : 'Pick a PDF file'),
          ),
          const Gap(24),

          // ── Paper style ──────────────────────────────────────────────────────
          Text('Paper Style', style: theme.textTheme.titleSmall),
          const Gap(8),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'plain', label: Text('Plain'), icon: Icon(Icons.article_outlined)),
              ButtonSegment(value: 'ruled', label: Text('Ruled'), icon: Icon(Icons.grid_3x3_outlined)),
              ButtonSegment(value: 'scan_texture', label: Text('Scan'), icon: Icon(Icons.texture)),
            ],
            selected: {_paperStyle},
            onSelectionChanged: (s) => setState(() => _paperStyle = s.first),
          ),
          const Gap(24),

          // ── Ink color ────────────────────────────────────────────────────────
          Text('Ink Color', style: theme.textTheme.titleSmall),
          const Gap(8),
          Row(
            children: [
              _ColorSwatch(color: const Color(0xFF23235A), selected: _inkColor == const Color(0xFF23235A), onTap: () => setState(() => _inkColor = const Color(0xFF23235A))),
              _ColorSwatch(color: Colors.black87, selected: _inkColor == Colors.black87, onTap: () => setState(() => _inkColor = Colors.black87)),
              _ColorSwatch(color: const Color(0xFF1A237E), selected: _inkColor == const Color(0xFF1A237E), onTap: () => setState(() => _inkColor = const Color(0xFF1A237E))),
              _ColorSwatch(color: const Color(0xFF4A148C), selected: _inkColor == const Color(0xFF4A148C), onTap: () => setState(() => _inkColor = const Color(0xFF4A148C))),
              _ColorSwatch(color: const Color(0xFF8B4513), selected: _inkColor == const Color(0xFF8B4513), onTap: () => setState(() => _inkColor = const Color(0xFF8B4513))),
            ],
          ),
          const Gap(24),

          // ── Jitter slider ──────────────────────────────────────────────────
          Text('Jitter: ${_jitter.toStringAsFixed(1)} px', style: theme.textTheme.titleSmall),
          const Gap(8),
          Slider(
            value: _jitter,
            min: 0,
            max: 10,
            divisions: 20,
            label: _jitter.toStringAsFixed(1),
            onChanged: (v) => setState(() => _jitter = v),
          ),
          const Gap(32),

          // ── Error ──────────────────────────────────────────────────────────
          if (convertState.error != null)
            Container(
              margin: const EdgeInsets.only(bottom: 16),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: theme.colorScheme.errorContainer,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                convertState.error!,
                style: TextStyle(color: theme.colorScheme.onErrorContainer),
              ),
            ),

          // ── Submit ─────────────────────────────────────────────────────────
          FilledButton.icon(
            onPressed: _canSubmit() ? _submit : null,
            icon: const Icon(Icons.auto_awesome),
            label: const Text('Convert to Handwriting'),
          ),
        ],
      ),
    );
  }

  bool _canSubmit() => _selectedProfileId != null && _pdfPath != null;

  Future<void> _pickPdf() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf'],
    );
    if (result != null && result.files.single.path != null) {
      setState(() => _pdfPath = result.files.single.path);
    }
  }

  Future<void> _submit() async {
    if (!_canSubmit()) return;
    // Convert ink color to "r,g,b" string
    final inkStr = '${_inkColor.red},${_inkColor.green},${_inkColor.blue}';
    await ref.read(convertProvider.notifier).submit(
          profileId: _selectedProfileId!,
          pdfPath: _pdfPath!,
          paperStyle: _paperStyle,
          inkColor: inkStr,
          jitter: _jitter,
        );
  }
}

// ── Progress view (shown during upload and polling) ───────────────────────────

class _ProgressView extends StatelessWidget {
  const _ProgressView({required this.state});
  final ConvertState state;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (state.isUploading) ...[
              CircularPercentIndicator(
                radius: 80,
                lineWidth: 10,
                percent: state.uploadProgress.clamp(0.0, 1.0),
                center: Text('${(state.uploadProgress * 100).toInt()}%',
                    style: theme.textTheme.headlineSmall),
                progressColor: cs.primary,
                backgroundColor: cs.primaryContainer,
                animation: true,
              ),
              const Gap(20),
              Text('Uploading PDF…', style: theme.textTheme.titleMedium),
            ] else if (state.job != null) ...[
              CircularPercentIndicator(
                radius: 80,
                lineWidth: 10,
                percent: state.job!.progress.clamp(0.0, 1.0),
                center: Text('${(state.job!.progress * 100).toInt()}%',
                    style: theme.textTheme.headlineSmall),
                progressColor: cs.primary,
                backgroundColor: cs.primaryContainer,
                animation: true,
                animateFromLastPercent: true,
              ),
              const Gap(20),
              Text(state.job!.message, style: theme.textTheme.titleMedium, textAlign: TextAlign.center),
              const Gap(8),
              Chip(
                label: Text(state.job!.status.label),
                avatar: state.job!.status.isActive
                    ? SizedBox.square(
                        dimension: 14,
                        child: CircularProgressIndicator(strokeWidth: 2, color: cs.primary),
                      )
                    : null,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ── Color swatch ───────────────────────────────────────────────────────────────

class _ColorSwatch extends StatelessWidget {
  const _ColorSwatch({
    required this.color,
    required this.selected,
    required this.onTap,
  });

  final Color color;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 40,
        height: 40,
        margin: const EdgeInsets.only(right: 8),
        decoration: BoxDecoration(
          color: color,
          shape: BoxShape.circle,
          border: Border.all(
            color: selected ? Theme.of(context).colorScheme.primary : Colors.transparent,
            width: 3,
          ),
        ),
      ),
    );
  }
}
