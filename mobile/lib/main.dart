import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'l10n/app_strings.dart';
import 'theme/tokens.dart';
import 'l10n/locale_controller.dart';
import 'services/api_client.dart';
import 'services/session.dart';
import 'screens/login_screen.dart';
import 'screens/root_shell.dart';

void main() {
  runApp(const SevakAIApp());
}

class SevakAIApp extends StatelessWidget {
  const SevakAIApp({super.key});

  @override
  Widget build(BuildContext context) {
    final api = ApiClient(); // point baseUrl (api_client.dart) at your dev machine's LAN IP
    // Rebuilds the whole app when the language changes, so every screen
    // re-reads its strings -- no restart, and no screen left behind in
    // the previous language.
    return ValueListenableBuilder<Locale>(
      valueListenable: appLocale,
      builder: (context, locale, _) => MaterialApp(
        title: 'SevakAI',
        theme: _buildTheme(),
        locale: locale,
        supportedLocales: AppStrings.supportedLocales,
        // Material and Widgets only. GlobalCupertinoLocalizations ships a
        // narrower locale set than Material does, and its load() asserts
        // on anything outside it -- so adding it here (nothing in this app
        // renders Cupertino widgets) would make picking a language it
        // doesn't cover fail while Hindi carried on working.
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
        ],
        // The worker's choice wins outright. Flutter's default resolution
        // falls back to supportedLocales.first (English) whenever it can't
        // match, which would silently ignore a language she just picked;
        // every code in the list is one this app translates, so hand it
        // straight back.
        localeResolutionCallback: (_, __) => locale,
        home: _Bootstrap(api: api),
        debugShowCheckedModeBanner: false,
      ),
    );
  }
}

/// The app theme, assembled entirely from [T]. Screens name tokens and
/// never raw hex, which is what keeps this and the three web dashboards
/// reading as one product.
///
/// Tuned for the conditions this app is actually used in: a mid-range
/// phone read outdoors, one-handed, between houses. Larger base text,
/// tap targets above the accessibility minimum, and real border contrast
/// instead of the pale greys that look elegant indoors and disappear on
/// a bright doorstep.
ThemeData _buildTheme() {
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(
      seedColor: T.forest,
      primary: T.forest,
      surface: T.surface,
      error: T.riskHigh,
    ),
  );

  return base.copyWith(
    scaffoldBackgroundColor: T.paper,
    appBarTheme: AppBarTheme(
      backgroundColor: T.paper,
      foregroundColor: T.ink,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: T.title,
      iconTheme: const IconThemeData(color: T.ink),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: T.surface,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(T.radius),
        side: const BorderSide(color: T.hairline),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: T.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: T.s3, vertical: T.s3),
      labelStyle: T.caption,
      floatingLabelStyle: T.caption.copyWith(color: T.forest, fontWeight: FontWeight.w600),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(T.radius)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(T.radius),
        borderSide: const BorderSide(color: T.hairline),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(T.radius),
        borderSide: const BorderSide(color: T.forest, width: 2),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(T.radius),
        borderSide: const BorderSide(color: T.riskHigh),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: T.forest,
        foregroundColor: Colors.white,
        // 52 clears the 48dp minimum with room to spare: this is tapped
        // in a hurry, outdoors, often one-handed.
        minimumSize: const Size.fromHeight(52),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(T.radius)),
        textStyle: T.strong.copyWith(fontSize: 16),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: T.ink,
        minimumSize: const Size.fromHeight(52),
        side: const BorderSide(color: T.hairline),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(T.radius)),
        textStyle: T.strong.copyWith(fontSize: 16),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: T.forest, textStyle: T.strong),
    ),
    listTileTheme: const ListTileThemeData(
      contentPadding: EdgeInsets.symmetric(horizontal: T.s4, vertical: T.s1),
      minVerticalPadding: T.s3,
    ),
    dividerTheme: const DividerThemeData(color: T.hairline, space: 1, thickness: 1),
    textTheme: base.textTheme.copyWith(
      displaySmall: T.display,
      titleLarge: T.title,
      titleMedium: T.section,
      bodyMedium: T.body,
      bodySmall: T.caption,
      labelSmall: T.micro,
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: T.ink,
      contentTextStyle: T.body.copyWith(color: Colors.white),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(T.radius)),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: T.surface,
      elevation: 3,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(T.radius),
        side: const BorderSide(color: T.hairline),
      ),
      textStyle: T.body,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: T.surface,
      indicatorColor: T.sage,
      elevation: 0,
      height: 68,
      surfaceTintColor: Colors.transparent,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => T.micro.copyWith(
          fontSize: 12,
          color: states.contains(WidgetState.selected) ? T.forest : T.slate,
          fontWeight: states.contains(WidgetState.selected) ? FontWeight.w700 : FontWeight.w500,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          color: states.contains(WidgetState.selected) ? T.forest : T.slate,
        ),
      ),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: T.forest, linearMinHeight: 3),
    // Quiet ripple: confirm the tap landed, don't perform.
    splashColor: T.forest.withValues(alpha: 0.07),
    highlightColor: T.forest.withValues(alpha: 0.03),
    // Android only, deliberately. CupertinoPageTransitionsBuilder lives in
    // package:flutter/cupertino.dart, and this app imports nothing from
    // Cupertino -- naming it here would mean pulling in a whole widget
    // library for one iOS transition the target device never uses. iOS
    // falls back to Flutter's platform default.
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {TargetPlatform.android: FadeUpwardsPageTransitionsBuilder()},
    ),
  );
}

/// Restores a saved login (if any) before showing anything else, so an
/// ASHA worker doesn't have to sign in every time she opens the app --
/// important when she's doing a dozen home visits in a day.
class _Bootstrap extends StatefulWidget {
  final ApiClient api;
  const _Bootstrap({required this.api});

  @override
  State<_Bootstrap> createState() => _BootstrapState();
}

class _BootstrapState extends State<_Bootstrap> {
  late final Future<Session?> _sessionFuture;

  @override
  void initState() {
    super.initState();
    // Language first, so the login screen already renders in her
    // language rather than flashing English for a frame.
    _sessionFuture = appLocale.load().then((_) => Session.restore());
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Session?>(
      future: _sessionFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
        final session = snapshot.data;
        if (session == null) {
          return LoginScreen(api: widget.api);
        }
        widget.api.setToken(session.token);
        return RootShell(api: widget.api, session: session);
      },
    );
  }
}
