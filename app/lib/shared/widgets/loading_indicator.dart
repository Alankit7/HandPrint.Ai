/// Reusable loading indicator widget.
library;

import 'package:flutter/material.dart';
import 'package:gap/gap.dart';

class LoadingIndicator extends StatelessWidget {
  const LoadingIndicator({
    this.message = 'Loading…',
    super.key,
  });

  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(),
          const Gap(16),
          Text(
            message,
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}
