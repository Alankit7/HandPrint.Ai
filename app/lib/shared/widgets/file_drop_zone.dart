/// Tappable drop zone card used on the upload screen.
library;

import 'package:flutter/material.dart';
import 'package:gap/gap.dart';

class FileDropZone extends StatelessWidget {
  const FileDropZone({
    required this.icon,
    required this.label,
    required this.hint,
    required this.onTap,
    this.isSelected = false,
    this.selectedLabel,
    super.key,
  });

  final IconData icon;
  final String label;
  final String hint;
  final VoidCallback onTap;
  final bool isSelected;
  final String? selectedLabel;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.all(24),
        decoration: BoxDecoration(
          color: isSelected
              ? colorScheme.primaryContainer
              : colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: isSelected ? colorScheme.primary : colorScheme.outline,
            width: isSelected ? 2 : 1,
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              isSelected ? Icons.check_circle_outline : icon,
              size: 48,
              color: isSelected ? colorScheme.primary : colorScheme.onSurfaceVariant,
            ),
            const Gap(12),
            Text(
              isSelected ? (selectedLabel ?? label) : label,
              style: textTheme.titleMedium?.copyWith(
                color: isSelected ? colorScheme.primary : colorScheme.onSurface,
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.center,
            ),
            const Gap(4),
            Text(
              isSelected ? 'Tap to change' : hint,
              style: textTheme.bodySmall?.copyWith(
                color: colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}
