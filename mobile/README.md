# SevakAI Mobile (Flutter)

ASHA worker Android app: login, patient list with risk badges, voice-record
a home visit, offline queue + auto-sync, follow-up task list (SRS FR-07).

## Building it

`flutter create .` has already been run and the result committed, so
`android/` and `ios/` are real, buildable platform folders -- including the
`RECORD_AUDIO` permission in `android/app/src/main/AndroidManifest.xml`,
which is the one that used to exist on a single laptop and nowhere else.

```bash
cd mobile
flutter pub get
flutter run            # with an emulator or device attached
```

Release APK, for handing to a demo device:

```bash
flutter build apk --release --dart-define=SEVAKAI_API=https://sevakai-api.onrender.com
# build/app/outputs/flutter-apk/app-release.apk
```

## Pointing at the backend

`lib/services/api_client.dart` defaults to the deployed API
(`https://sevakai-api.onrender.com`), so an APK built with no extra flags
works out of the box. Override it at build time:

```bash
flutter run --dart-define=SEVAKAI_API=http://10.0.2.2:8000        # emulator -> localhost
flutter run --dart-define=SEVAKAI_API=http://192.168.1.42:8000    # device -> your LAN IP
```

Plain `http` works in debug builds only --
`android/app/src/debug/AndroidManifest.xml` permits cleartext there and
nowhere else, so a release build must be given an `https` URL.

## Layout

```
lib/
  main.dart                  App entry point, launches LoginScreen
  models/                    Patient, FollowupTask -- mirror backend Pydantic schemas
  services/
    api_client.dart          HTTP calls to the FastAPI backend
    offline_queue.dart       sqflite-backed sync_queue (offline recording)
    sync_service.dart        Watches connectivity, flushes the queue automatically
  screens/
    login_screen.dart        Phone + PIN -> JWT (demo: 9999999999 / 1234)
    patient_list_screen.dart FR-07.2: patient list + risk badges
    voice_record_screen.dart FR-01.1/01.3: record, submit or queue offline
    task_list_screen.dart    FR-07.3: pending follow-ups sorted by urgency
  widgets/risk_badge.dart    RED/YELLOW/GREEN dot
```

## Still to do

- **Run it on a real low-end Android handset.** This is the only item left
  that is not code: the app has been exercised on emulators and laptops,
  and its whole premise is a ~2GB-RAM phone in a village. Microphone
  permissions, recording behaviour, memory pressure and offline sync on a
  flaky connection are all unverified on real hardware.
- **Usability testing with a practising ASHA worker.** The design follows
  published literature on ASHA workload and NHM protocol documents, not
  observed use.

Done, and previously listed here as outstanding: `SyncService.start()` is
wired (`lib/screens/root_shell.dart`), login persists across restarts via
platform secure storage (`lib/main.dart`, `lib/services/session.dart`), and
the UI is localised into six languages (`lib/l10n/app_strings.dart`).
