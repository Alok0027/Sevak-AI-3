// Replaces the counter test `flutter create` generates. That test asked for
// a class named MyApp, which this app has never had (the root widget is
// SevakAIApp), so it failed to compile -- `flutter analyze` reported one
// error and `flutter test` could not run at all.
//
// What it checks instead is the thing that actually broke here once: for a
// while, switching language only worked for Hindi. Every other language
// silently rendered English, because the lookup resolved through a
// localizations delegate whose locale set did not cover them. That is
// invisible in review -- the code reads correctly in every language -- and
// obvious the moment you assert on it.

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:sevakai_mobile/l10n/app_strings.dart';

/// The one framework warning this app raises on purpose.
///
/// MaterialApp always includes a Cupertino localizations delegate, and in
/// debug it warns when any supported locale is outside some delegate's
/// range. None of ta/te/bn/mr are in Cupertino's set, so the warning fires
/// five times on startup.
///
/// The fix it suggests -- GlobalMaterialLocalizations.delegates, plural --
/// is the thing that caused the bug this file exists to catch: that list
/// includes GlobalCupertinoLocalizations, whose load() asserts on a locale
/// it does not cover, so picking Tamil threw where Hindi worked. Nothing in
/// this app renders a Cupertino widget, so the warning is about strings
/// that are never asked for.
///
/// Matched narrowly and re-raised otherwise, so this suppresses exactly the
/// known-benign message and nothing else. If it ever stops firing, delete
/// this -- the app is not relying on it.
const _knownBenign = 'is not supported by all of its localization delegates';

/// Renders one key under one locale, mirroring main.dart's MaterialApp
/// setup exactly -- same delegates, same resolution callback. A test that
/// configured localization differently from the app would pass while the
/// app was broken, which is precisely the failure it exists to catch.
Future<String> _render(WidgetTester tester, String code, String key) async {
  late String value;

  final previous = FlutterError.onError;
  final unexpected = <FlutterErrorDetails>[];
  FlutterError.onError = (details) {
    if (!'${details.exception}'.contains(_knownBenign)) {
      unexpected.add(details);
    }
  };

  try {
    await tester.pumpWidget(
      MaterialApp(
        locale: Locale(code),
        supportedLocales: AppStrings.supportedLocales,
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
        ],
        localeResolutionCallback: (_, __) => Locale(code),
        home: Builder(
          builder: (context) {
            value = AppStrings.of(context, key);
            return const SizedBox.shrink();
          },
        ),
      ),
    );
  } finally {
    FlutterError.onError = previous;
  }

  if (unexpected.isNotEmpty) {
    fail('locale "$code" raised ${unexpected.length} unexpected error(s):\n'
        '${unexpected.map((d) => d.exception).join('\n')}');
  }
  return value;
}

void main() {
  test('all six SRS languages are declared', () {
    expect(AppStrings.supportedLanguages.keys.toList(),
        ['en', 'hi', 'mr', 'ta', 'te', 'bn']);
    expect(AppStrings.supportedLocales.length, 6);
  });

  testWidgets('every language resolves its own strings, not English',
      (tester) async {
    final english = await _render(tester, 'en', 'signIn');
    expect(english, 'Sign in');

    for (final code
        in AppStrings.supportedLanguages.keys.where((c) => c != 'en')) {
      final translated = await _render(tester, code, 'signIn');
      expect(translated, isNotEmpty, reason: '$code returned an empty string');
      expect(translated, isNot(english),
          reason: '$code fell back to English -- the language picker would '
              'appear to do nothing for this language');
    }
  });

  testWidgets('a key no language defines falls back to the key itself',
      (tester) async {
    // Documented behaviour, and the reason a half-translated key is a
    // cosmetic problem rather than a crash: AppStrings.of returns
    // _all[code] ?? _en ?? key. Asserting it so the fallback chain cannot
    // be "simplified" into a null dereference later.
    expect(
        await _render(tester, 'hi', 'noSuchKeyAnywhere'), 'noSuchKeyAnywhere');
  });
}
