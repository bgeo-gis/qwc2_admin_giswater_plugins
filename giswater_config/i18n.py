"""
Copyright © 2025 by BGEO. All rights reserved.
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
import json
import os
from flask import request

# Try to import the admin gui i18n system
try:
    from utils import i18n as admin_i18n
    ADMIN_I18N_AVAILABLE = True
except ImportError:
    ADMIN_I18N_AVAILABLE = False


class GiswaterConfigI18n:
    """Internationalization handler for giswater_config plugin"""

    def __init__(self, plugin_dir):
        self.plugin_dir = plugin_dir
        self.translations_dir = os.path.join(plugin_dir, 'translations')
        self._translations = {}
        self._load_translations()

    def _load_translations(self):
        """Load all translation files"""
        for lang in ['es', 'ca', 'en']:
            translation_file = os.path.join(self.translations_dir, f'{lang}.json')
            if os.path.exists(translation_file):
                try:
                    with open(translation_file, 'r', encoding='utf-8') as f:
                        self._translations[lang] = json.load(f)
                except Exception as e:
                    print(f"Error loading translation file {lang}.json: {e}")

    def get_language(self):
        """Get current language from request or default to Spanish"""
        # Try to get language from request args or headers
        if hasattr(request, 'args') and request.args.get('lang'):
            lang = request.args.get('lang')
            print(f"DEBUG: Language from URL param: {lang}")
            return lang

        # Try to get language from admin gui if available
        if ADMIN_I18N_AVAILABLE:
            try:
                # Try to get a sample translation to detect admin gui language
                admin_lang = admin_i18n('interface.common.add')
                if admin_lang == 'Añadir':  # Spanish
                    return 'es'
                elif admin_lang == 'Afegir':  # Catalan
                    return 'ca'
                elif admin_lang == 'Add':  # English
                    return 'en'
            except Exception as e:
                print(f"DEBUG: Error detecting admin GUI language: {e}")

        # Fallback to Accept-Language header
        if hasattr(request, 'headers'):
            accept_language = request.headers.get('Accept-Language', '')
            print(f"DEBUG: Accept-Language header: {accept_language}")

            # Simple check: if Spanish is mentioned anywhere, use Spanish
            if 'es' in accept_language and 'ca' not in accept_language:
                print("DEBUG: Spanish detected in Accept-Language, using Spanish")
                return 'es'
            elif 'ca' in accept_language:
                print("DEBUG: Catalan detected in Accept-Language, using Catalan")
                return 'ca'
            elif 'en' in accept_language:
                print("DEBUG: English detected in Accept-Language, using English")
                return 'en'

        print("DEBUG: Using default Spanish (es)")
        return 'es'  # Default to Spanish

    def translate(self, key, **kwargs):
        """Translate a key with optional formatting parameters"""
        # First try to get translation from admin gui if available
        if ADMIN_I18N_AVAILABLE and key.startswith('interface.'):
            try:
                return admin_i18n(key, **kwargs)
            except:
                pass

        # Fall back to plugin translations
        lang = self.get_language()
        translations = self._translations.get(lang, self._translations.get('es', {}))

        text = translations.get(key, key)

        # Format with provided parameters
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):
                # If formatting fails, return the text as is
                pass

        return text

    def get_all_translations(self):
        """Get all translations for current language"""
        lang = self.get_language()
        return self._translations.get(lang, self._translations.get('es', {}))

    def __call__(self, key, **kwargs):
        """Make the object callable for template compatibility"""
        return self.translate(key, **kwargs)


# Global instance
plugin_dir = os.path.dirname(os.path.abspath(__file__))
i18n = GiswaterConfigI18n(plugin_dir)
