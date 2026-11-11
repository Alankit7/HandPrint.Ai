/// Holds the user's selected files before submission.
library;

class JobSubmission {
  const JobSubmission({
    required this.pdfPath,
    required this.samplePaths,
  });

  /// Absolute path to the selected PDF.
  final String pdfPath;

  /// Absolute paths to the selected handwriting sample images.
  final List<String> samplePaths;

  String get pdfFileName => pdfPath.split('/').last;

  bool get isValid => pdfPath.isNotEmpty && samplePaths.isNotEmpty;
}
