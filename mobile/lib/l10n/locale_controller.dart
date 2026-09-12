import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_strings.dart';

/// The app's current UI language, persisted to the device.
///
/// Saved with the same shared_preferences store the login session uses,
/// so a worker who picks Marathi once never sees English again -- and,
/// importantly, the choice survives a reinstallless restart on a phone
/// that gets rebooted between visits.
///
/// A single shared instance rather than a value threaded through every
/// constructor: the language is genuinely global to the app, and the one
/// screen that changes it (the app-bar picker) sits far from the ones
/// that read it.
class LocaleController extends ValueNotifier<Locale> {
  static const _prefsKey = 'sevakai_language_code';

  LocaleController() : super(const Locale('en'));

  /// Restores the saved language. Falls back to English rather than the
  /// phone's own locale: the app is only translated into a handful of
  /// languages, and silently landing a Kannada-phone user in English is
  /// less confusing than landing them in a half-translated Tamil.
  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final code = prefs.getString(_prefsKey);
    if (code != null && AppStrings.supportedLanguages.containsKey(code)) {
      value = Locale(code);
    }
  }

  Future<void> setLanguage(String code) async {
    if (!AppStrings.supportedLanguages.containsKey(code)) return;
    value = Locale(code);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, code);
  }
}

final appLocale = LocaleController();
