/// Profiles screen — list writer profiles, create new ones, start training.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import 'package:gap/gap.dart';
import 'package:percent_indicator/percent_indicator.dart';

import '../../core/models/profile.dart';
import '../../shared/widgets/empty_state.dart';
import '../../shared/widgets/error_state.dart';
import '../../shared/widgets/loading_indicator.dart';
import 'profiles_provider.dart';

class ProfilesScreen extends ConsumerWidget {
  const ProfilesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(profilesProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Profiles')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _showCreateSheet(context, ref),
        icon: const Icon(Icons.add),
        label: const Text('New Profile'),
      ),
      body: _buildBody(context, ref, state),
    );
  }

  Widget _buildBody(BuildContext context, WidgetRef ref, ProfilesState state) {
    if (state.isUploading) {
      return _UploadProgress(state: state);
    }
    if (state.profiles.isEmpty) {
      return EmptyState(
        icon: Icons.person_outline,
        title: 'No profiles yet',
        message: 'Create a writer profile by uploading 15–30 handwriting sample images.',
        actionLabel: 'New Profile',
        onAction: () => _showCreateSheet(context, ref),
      );
    }
    if (state.error != null && state.profiles.isEmpty) {
      return ErrorState(message: state.error!, onRetry: () => ref.read(profilesProvider.notifier).clearErrors());
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: state.profiles.length,
      itemBuilder: (context, index) {
        final profile = state.profiles[index];
        final isTraining = state.trainingProfileId == profile.id;
        return _ProfileCard(
          profile: profile,
          isTraining: isTraining,
          onTrain: () => ref.read(profilesProvider.notifier).startTraining(profile.id),
        );
      },
    );
  }

  void _showCreateSheet(BuildContext context, WidgetRef ref) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (context) => _CreateProfileSheet(ref: ref),
    );
  }
}

// ── Profile card ──────────────────────────────────────────────────────────────

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({
    required this.profile,
    required this.isTraining,
    required this.onTrain,
  });

  final Profile profile;
  final bool isTraining;
  final VoidCallback onTrain;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    profile.name,
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
                  ),
                ),
                _StatusChip(status: profile.status),
              ],
            ),
            const Gap(8),
            Text(
              '${profile.sampleCount} sample images',
              style: theme.textTheme.bodySmall?.copyWith(color: colorScheme.onSurfaceVariant),
            ),
            if (isTraining || profile.status == ProfileStatus.training) ...[
              const Gap(12),
              LinearPercentIndicator(
                percent: profile.trainProgress.clamp(0.0, 1.0),
                progressColor: colorScheme.primary,
                backgroundColor: colorScheme.primaryContainer,
                barRadius: const Radius.circular(8),
                lineHeight: 8,
                animation: true,
                animateFromLastPercent: true,
              ),
              const Gap(4),
              Text(
                'Training… ${(profile.trainProgress * 100).toInt()}%',
                style: theme.textTheme.bodySmall?.copyWith(color: colorScheme.primary),
              ),
            ],
            if (profile.status == ProfileStatus.failed && profile.error != null) ...[
              const Gap(8),
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: colorScheme.errorContainer,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  profile.error!,
                  style: theme.textTheme.bodySmall?.copyWith(color: colorScheme.onErrorContainer),
                ),
              ),
            ],
            if (profile.status == ProfileStatus.pending || profile.status == ProfileStatus.failed) ...[
              const Gap(12),
              FilledButton.tonalIcon(
                onPressed: onTrain,
                icon: const Icon(Icons.school_outlined),
                label: Text(profile.status == ProfileStatus.failed ? 'Retry Training' : 'Start Training'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ── Status chip ───────────────────────────────────────────────────────────────

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});
  final ProfileStatus status;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final (label, color) = switch (status) {
      ProfileStatus.pending => ('Pending', cs.secondary),
      ProfileStatus.training => ('Training', cs.primary),
      ProfileStatus.ready => ('Ready', Colors.green),
      ProfileStatus.failed => ('Failed', cs.error),
    };
    return Chip(
      label: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w600, fontSize: 12)),
      backgroundColor: color.withOpacity(0.12),
      side: BorderSide.none,
      padding: EdgeInsets.zero,
      visualDensity: VisualDensity.compact,
    );
  }
}

// ── Upload progress ───────────────────────────────────────────────────────────

class _UploadProgress extends StatelessWidget {
  const _UploadProgress({required this.state});
  final ProfilesState state;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularPercentIndicator(
              radius: 60,
              lineWidth: 8,
              percent: state.uploadProgress.clamp(0.0, 1.0),
              center: Text('${(state.uploadProgress * 100).toInt()}%'),
              progressColor: Theme.of(context).colorScheme.primary,
              backgroundColor: Theme.of(context).colorScheme.primaryContainer,
              animation: true,
            ),
            const Gap(16),
            const Text('Uploading samples…'),
          ],
        ),
      ),
    );
  }
}

// ── Create profile bottom sheet ────────────────────────────────────────────────

class _CreateProfileSheet extends StatefulWidget {
  const _CreateProfileSheet({required this.ref});
  final WidgetRef ref;

  @override
  State<_CreateProfileSheet> createState() => _CreateProfileSheetState();
}

class _CreateProfileSheetState extends State<_CreateProfileSheet> {
  final _nameController = TextEditingController();
  final _samplePaths = <String>[];
  bool _isSubmitting = false;

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  Future<void> _pickImages() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.image,
      allowMultiple: true,
    );
    if (result != null) {
      setState(() {
        _samplePaths.addAll(result.files.where((f) => f.path != null).map((f) => f.path!));
      });
    }
  }

  Future<void> _submit() async {
    if (_nameController.text.trim().isEmpty || _samplePaths.isEmpty) return;
    setState(() => _isSubmitting = true);

    final notifier = widget.ref.read(profilesProvider.notifier);
    final profileId = await notifier.createProfile(
      name: _nameController.text.trim(),
      samplePaths: _samplePaths,
    );

    if (mounted) {
      setState(() => _isSubmitting = false);
      if (profileId != null) {
        Navigator.of(context).pop();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Profile "$profileId" created. Tap Train to start fine-tuning.')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 24,
        right: 24,
        top: 24,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('New Writer Profile', style: Theme.of(context).textTheme.headlineSmall),
          const Gap(20),
          TextField(
            controller: _nameController,
            decoration: const InputDecoration(
              labelText: 'Writer name',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.person_outline),
            ),
          ),
          const Gap(16),
          OutlinedButton.icon(
            onPressed: _pickImages,
            icon: const Icon(Icons.photo_library_outlined),
            label: Text(_samplePaths.isEmpty
                ? 'Select 15–30 sample images'
                : '${_samplePaths.length} image(s) selected'),
          ),
          if (_samplePaths.isNotEmpty) ...[
            const Gap(8),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: List.generate(_samplePaths.length, (i) {
                final name = _samplePaths[i].split('/').last;
                return Chip(
                  label: Text(name, style: const TextStyle(fontSize: 11)),
                  deleteIcon: const Icon(Icons.close, size: 16),
                  onDeleted: () => setState(() => _samplePaths.removeAt(i)),
                );
              }),
            ),
          ],
          const Gap(20),
          FilledButton.icon(
            onPressed: (_isSubmitting ||
                    _nameController.text.trim().isEmpty ||
                    _samplePaths.isEmpty)
                ? null
                : _submit,
            icon: _isSubmitting
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Icon(Icons.upload),
            label: Text(_isSubmitting ? 'Uploading…' : 'Create Profile'),
          ),
        ],
      ),
    );
  }
}
