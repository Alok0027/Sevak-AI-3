import 'package:flutter/foundation.dart';

/// One notifier the whole bottom-nav shell shares, so a visit recorded on
/// any screen is visible on every other screen.
///
/// The three tabs live in an IndexedStack, which keeps all of them alive
/// for the life of the session. That is what makes switching tabs instant,
/// but it also means each tab's `initState` runs exactly once -- at login.
/// Without a signal like this one, "My Patients" keeps showing the list as
/// it was when the ASHA signed in: a patient she has just recorded a HIGH
/// visit for still reads "no visits recorded yet", with no risk on her
/// row. She then records the same visit a second time from the patient's
/// own screen, because the first one looks like it never landed.
///
/// Ping this whenever server-side state changes (a visit submitted, a
/// follow-up completed) or when she moves between tabs; every listening
/// screen refetches.
class RefreshSignal extends ValueNotifier<int> {
  RefreshSignal() : super(0);

  void ping() => value++;
}
