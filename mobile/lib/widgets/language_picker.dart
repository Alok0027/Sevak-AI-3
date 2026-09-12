import 'package:flutter/material.dart';

import '../l10n/app_strings.dart';
import '../l10n/locale_controller.dart';

/// The app-bar language switcher.
///
/// Lives in the app bar on every screen rather than behind a settings
/// page, for one practical reason: if someone changes the language to a
/// script they can't read, they still need a way back. A globe icon in a
/// fixed position is recognisable whatever the current language is, and
/// each option is written in its own script, so nobody has to read
/// English to find their language.
class LanguagePicker extends StatelessWidget {
  const LanguagePicker({super.key});

  @override
  Widget build(BuildContext context) {
    final current = Localizations.localeOf(context).languageCode;

    return PopupMenuButton<String>(
      icon: const Icon(Icons.language),
      tooltip: tr(context, 'chooseLanguage'),
      onSelected: appLocale.setLanguage,
      itemBuilder: (context) => [
        for (final entry in AppStrings.supportedLanguages.entries)
          PopupMenuItem<String>(
            value: entry.key,
            child: Row(
              children: [
                SizedBox(
                  width: 26,
                  child: entry.key == current
                      ? const Icon(Icons.check, size: 18, color: Color(0xFF1F6F4A))
                      : null,
                ),
                Text(
                  entry.value,
                  style: TextStyle(
                    fontWeight: entry.key == current ? FontWeight.w700 : FontWeight.w500,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
