# Handprint AI — Comprehensive Investigation Report

## Summary

The project is in generally good structural shape. No build-breaking syntax errors exist in any file. However, **10 real bugs or misconfigurations** were found across the backend Python code, the Flutter Dart code, and the Docker/deployment layer. The most critical are: (1) a **wrong-type argument bug in the Flutter result download callback** that always stores the raw `received` bytes integer instead of a 0–1 fraction as a progress value; (2) **`train_worker.py` accesses `profile.sample_dir` after the SQLAlchemy session is closed**, which will raise a `DetachedInstanceError` at runtime; (3) the **`apiClientProvider` in `api_client.dart` unconditionally throws `UnimplementedError`** but is never actually overridden in `ProviderScope`, making it dead/dangerous code; and (4) the **history feature is wired only to display entries but no code ever calls `HistoryNotifier.add()`**, so the history screen will always be empty.

---

## Findings

### ISSUE 1 — `result_provider.dart`: Wrong callback signature on `downloadResult` (type/logic bug)

**File:** `app/lib/features/result/result_provider.dart`, lines 66–69

**Problem:**  
`ApiClient.downloadResult` accepts `onProgress: void Function(double progress)?` — a single-argument callback that receives a pre-computed fraction 0.0–1.0. However, `ResultNotifier.download()` passes a two-argument closure:

```dart
onProgress: (received, total) {
  // onProgress gives us a double 0.0–1.0
  state = state.copyWith(downloadProgress: received);
},
```

The parameter type of `onProgress` in `ApiClient` (see `api_client.dart` line 162–176) is `void Function(double progress)?`. Passing a `(received, total)` two-argument lambda to a one-argument function parameter is a **Dart type error**. The analyzer will flag this as `The argument type 'Null Function(dynamic, dynamic)' can't be assigned to the parameter type 'void Function(double)?'`.

Even if the types were compatible, `received` would be the raw bytes received (an `int`, not a 0–1 fraction) rather than the computed fraction, so the progress bar would display wrong values.

**Fix:**

```dart
onProgress: (progress) {
  state = state.copyWith(downloadProgress: progress);
},
```

---

### ISSUE 2 — `train_worker.py`: `profile.sample_dir` accessed after DB session closes (DetachedInstanceError)

**File:** `backend/app/workers/train_worker.py`, lines 30–43

**Problem:**  
After the first `with get_db_ctx() as db:` block closes (at line 38), the `profile` ORM object becomes detached from the SQLAlchemy session. Line 43 then accesses `profile.sample_dir` on the detached object:

```python
with get_db_ctx() as db:
    profile: Profile | None = db.get(Profile, profile_id)
    ...
    profile.status = ProfileStatus.TRAINING
    profile.train_progress = 0.0
    profile.error = None

# ← session is now closed; profile is detached

checkpoint_out = settings.output_dir / "checkpoints" / profile_id
checkpoint_out.mkdir(parents=True, exist_ok=True)

sample_dir = Path(profile.sample_dir) if profile.sample_dir else None  # ← DETACHED ACCESS
```

With SQLite + `StaticPool` this may work by accident (the session's identity map may still hold the value), but under `NullPool` (production recommendation, mentioned in `session.py` comments) or any multi-worker setup, this raises `sqlalchemy.orm.exc.DetachedInstanceError`.

**Fix:** Read `profile.sample_dir` inside the `with` block and store it in a local variable, just as `convert_worker.py` correctly does for `checkpoint_path` and `input_pdf`:

```python
sample_dir_path: str | None = None
with get_db_ctx() as db:
    profile = db.get(Profile, profile_id)
    if profile is None:
        logger.error("[train] Profile %s not found — aborting.", profile_id)
        return
    profile.status = ProfileStatus.TRAINING
    profile.train_progress = 0.0
    profile.error = None
    sample_dir_path = profile.sample_dir  # ← capture before session closes

# ...
sample_dir = Path(sample_dir_path) if sample_dir_path else None
```

---

### ISSUE 3 — `api_client.dart`: Dead `apiClientProvider` throws but is never properly overridden

**File:** `app/lib/core/network/api_client.dart`, lines 22–27

**Problem:**  
`apiClientProvider` is declared as:

```dart
final apiClientProvider = Provider<ApiClient>((ref) {
  throw UnimplementedError('apiClientProvider must be overridden in ProviderScope');
});
```

The comment says it "must be overridden in ProviderScope", but the actual `ProviderScope` in `main.dart` has no overrides array. All three feature providers (`convertProvider`, `profilesProvider`, `resultProvider`) correctly use `settingsApiClientProvider` instead. The `apiClientProvider` symbol is therefore unreachable live code that will crash any consumer that accidentally watches it. It should be removed to avoid future confusion and accidental use.

**Fix:** Remove `apiClientProvider` and `apiClientFactoryProvider` from `api_client.dart`, since neither is consumed anywhere in the app.

---

### ISSUE 4 — `history_provider.dart` / UI: History is never populated

**Files:** `app/lib/features/history/history_provider.dart`, `app/lib/features/result/result_provider.dart`

**Problem:**  
`HistoryNotifier` has a fully working `add(HistoryEntry)` method and `HistoryScreen` reads from `historyProvider`. However, **no code anywhere in the app ever calls `historyProvider.notifier.add()`**. When a job completes in `result_provider.dart`, the download is performed and `localPath` is stored locally in `ResultState`, but nothing writes to the history store. The History tab will always show the "No history yet" empty state regardless of how many conversions are completed.

**Fix:** In `ResultNotifier.download()`, after a successful download, add the entry to history:

```dart
// After state = state.copyWith(isDownloading: false, downloadProgress: 1.0, localPath: savePath);
ref.read(historyProvider.notifier).add(HistoryEntry(
  jobId: jobId,
  profileName: '', // profileName requires passing it into ResultNotifier or fetching from profilesProvider
  completedAt: DateTime.now(),
  localPath: savePath,
));
```

This requires either passing `profileName` into `ResultNotifier` via the `.family` parameter (currently only `jobId` is passed) or fetching it from `profilesProvider`. The cleanest fix is to change the family parameter to a record/class containing both `jobId` and `profileName`.

---

### ISSUE 5 — `profiles_screen.dart`: `EmptyState`/`ErrorState` ordering logic is wrong

**File:** `app/lib/features/profiles/profiles_screen.dart`, lines 37–42

**Problem:**  
The body-building logic checks `state.error != null && state.profiles.isEmpty` **after** returning early for `state.profiles.isEmpty`. This means the `ErrorState` widget can never be shown:

```dart
if (state.isUploading) {
  return _UploadProgress(state: state);
}
if (state.profiles.isEmpty) {
  return EmptyState(...);  // ← always returns here if list is empty
}
if (state.error != null && state.profiles.isEmpty) {  // ← unreachable
  return ErrorState(...);
}
```

If `profiles` is empty and there's also an error (e.g., the profile creation call failed and the list is still empty), only the `EmptyState` is shown, never the `ErrorState`.

**Fix:** Check the error condition before the empty check:

```dart
if (state.isUploading) {
  return _UploadProgress(state: state);
}
if (state.error != null && state.profiles.isEmpty) {
  return ErrorState(message: state.error!, onRetry: () => ref.read(profilesProvider.notifier).clearErrors());
}
if (state.profiles.isEmpty) {
  return EmptyState(...);
}
```

---

### ISSUE 6 — `profiles.py`: `create_profile` saves uploaded files synchronously inside an `async` route handler (blocking I/O)

**File:** `backend/app/api/v1/profiles.py`, lines 68–72

**Problem:**  
`create_profile` is an `async def` route handler. It calls `save_upload(img, dest)` synchronously in a loop for every uploaded image. `save_upload` uses `shutil.copyfileobj` — a blocking I/O call. Running blocking I/O in an `async` handler blocks the uvicorn event loop for the full duration of all uploads, preventing other requests from being served concurrently.

The same issue applies to `validate_image` / `validate_pdf`, which call `upload.file.seek()` and `upload.file.tell()` synchronously. These are lighter but still block the event loop.

**Fix:** Either convert the route to `def` (synchronous, run in a threadpool by FastAPI automatically) or use `await asyncio.get_event_loop().run_in_executor(None, save_upload, img, dest)`. Converting to `def` is simpler and is exactly what `start_training` and `get_profile` already do.

```python
# Change:
async def create_profile(...) -> ProfileResponse:
# To:
def create_profile(...) -> ProfileResponse:
```

(Also change `async def create_convert_job` in `jobs.py` for the same reason.)

---

### ISSUE 7 — `render.py`: `_paste_rgb` calls `bbox_idx_1` before it is defined (name resolution at call time)

**File:** `backend/app/ml/render.py`, lines ~840–855

**Problem:**  
`_paste_rgb` calls `bbox_idx_1(bbox_pt)` on line 845. `bbox_idx_1` is defined on line 852, **after** `_paste_rgb`. In Python, this is not a syntax error (functions are resolved at call time, not at definition time), but it is a code quality/ordering issue that is confusing and fragile. Additionally, `bbox_idx_1` is a trivially pointless wrapper (`return bbox[1]`) used only once. The comment "helper for readability" is misleading — `bbox_pt[1]` is clearer than `bbox_idx_1(bbox_pt)`.

**Severity:** Low — works correctly at runtime because Python resolves names at call time, not definition time. However it violates the convention established throughout the rest of the file (helpers defined before use).

**Fix:** Inline the call: replace `bbox_idx_1(bbox_pt)` with `bbox_pt[1]` and remove the `bbox_idx_1` function.

---

### ISSUE 8 — `docker-compose.yml`: `version` key is obsolete (Docker Compose v2 warning)

**File:** `docker-compose.yml`, line 1

**Problem:**  
```yaml
version: "3.9"
```
Docker Compose v2 (the current CLI, `docker compose`) ignores the `version` key and emits a warning: `the attribute 'version' is obsolete, it will be ignored`. `docker-compose.prod.yml` correctly omits it.

**Fix:** Remove the `version: "3.9"` line from `docker-compose.yml`.

---

### ISSUE 9 — `Dockerfile.prod` builder stage copies wrong requirements file

**File:** `backend/Dockerfile.prod`, lines 20–26

**Problem:**  
The builder stage copies:
```dockerfile
COPY requirements.txt requirements/base.txt ./requirements/
```

This copies the root `requirements.txt` (which includes dev/test tools: `pytest`, `httpx`, `pytest-mock`, `pytest-asyncio`) and `requirements/base.txt` into the build context. The comment says "Install from the base (runtime-only) requirements — test deps are excluded", but the destination path `./requirements/` means it installs from `requirements/base.txt`. The root `requirements.txt` is copied but never used in the production build — it just wastes layer space. Additionally, there is no COPY for `requirements/gpu.txt`, which is needed if GPU training packages beyond the base PyTorch image are required.

**Fix:** Remove the unnecessary root `requirements.txt` copy:
```dockerfile
COPY requirements/base.txt ./requirements/
```

---

### ISSUE 10 — Flutter test: `notifier.state =` direct assignment is not valid on a `StateNotifier`

**Files:** `app/test/widgets/convert_polling_test.dart` (line 188), `app/test/widgets/profiles_polling_test.dart` (lines 58, 76, 93, 109, 127, 145, 190, 256)

**Problem:**  
The tests directly assign to `notifier.state`:
```dart
notifier.state = notifier.state.copyWith(jobId: 'job-1', ...);
```

In Riverpod, `StateNotifier.state` has a **protected setter** — it can only be set from within the `StateNotifier` subclass itself. Setting it from outside the class (including tests) is not allowed in Riverpod 2.x and will produce a `StateError` or compile-time error depending on the Dart analysis mode. The `flutter_riverpod: ^2.5.1` declared in `pubspec.yaml` enforces this.

**Fix:** Add a `@visibleForTesting` test-only setter method to each notifier, or expose a `seedState` method used only in tests:

```dart
// In ConvertNotifier:
@visibleForTesting
void seedState(ConvertState s) => state = s;
```

Then in tests:
```dart
notifier.seedState(notifier.state.copyWith(jobId: 'job-1', ...));
```

---

## Minor / Informational Notes

### NOTE A — `AppConfig.load()` is called twice
`main.dart` calls `await dotenv.load(fileName: '.env')` directly, and `AppConfig.load()` (which does the same thing) is defined but never called. This is harmless duplication, but `AppConfig.load()` should either be called in `main()` or removed.

### NOTE B — `ProfileCreate` schema is imported but never used
`app/db/schemas.py` imports and defines `ProfileCreate`, and `profiles.py` imports it (`from app.db.schemas import MessageResponse, ProfileCreate, ProfileResponse`) but never uses it — the route reads form fields directly. This is dead code.

### NOTE C — `analysis_options.yaml` is not read
`app/analysis_options.yaml` exists but was not shown in directory listing output. If it is empty or missing Flutter-recommended lints, the Issues 10 may be suppressed. It should include `package:flutter_lints/flutter.yaml` to surface protected-setter access in tests.

### NOTE D — `save_upload` is synchronous but `UploadFile.file` is a `SpooledTemporaryFile`
Using `shutil.copyfileobj(upload.file, f)` is synchronous. For large uploads in production this is acceptable if the route is changed from `async def` to `def` (see Issue 6), which makes FastAPI run it in a thread automatically.

### NOTE E — `ProfileStatus` is compared as string vs enum in `start_training`
In `profiles.py` line 56: `profile.status in (ProfileStatus.TRAINING, ProfileStatus.READY)`. Because `ProfileStatus` extends both `str` and `PyEnum`, and the ORM stores the value as a plain string column, this comparison works. But it's fragile — SQLAlchemy may return a plain `str` from the DB, and `str in (ProfileStatus.TRAINING, ...)` works only because `ProfileStatus` inherits from `str`. This is intentional and works correctly, but worth noting.

---

## Conclusions and Recommended Fix Priority

| Priority | Issue | File(s) | Impact |
|---|---|---|---|
| **P0 — Must fix** | Issue 1: Wrong `onProgress` signature in `result_provider.dart` | `result_provider.dart:66` | Type error, wrong progress values |
| **P0 — Must fix** | Issue 2: Detached SQLAlchemy access in `train_worker.py` | `train_worker.py:43` | Runtime crash in production |
| **P1 — Should fix** | Issue 4: History never populated | `result_provider.dart`, `history_provider.dart` | History tab permanently empty |
| **P1 — Should fix** | Issue 5: `ErrorState` unreachable in `profiles_screen.dart` | `profiles_screen.dart:37–42` | Error state never displayed |
| **P1 — Should fix** | Issue 10: `notifier.state =` in tests will fail | Both `*_polling_test.dart` files | Tests will not compile/run |
| **P2 — Recommended** | Issue 3: Dead `apiClientProvider` throws | `api_client.dart:22–27` | Code clarity, crash risk |
| **P2 — Recommended** | Issue 6: Blocking I/O in async route | `profiles.py:40`, `jobs.py:52` | Event loop stall under load |
| **P3 — Low** | Issue 7: `bbox_idx_1` defined after first use | `render.py:845,852` | Code clarity only |
| **P3 — Low** | Issue 8: `version` in docker-compose.yml | `docker-compose.yml:1` | Docker warning |
| **P3 — Low** | Issue 9: Dockerfile.prod copies unused file | `Dockerfile.prod:20` | Unnecessary image bloat |
