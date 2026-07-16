"""
Copyright © 2026 by BGEO. All rights reserved.
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
import json
import os
from flask import request

try:
    from utils import i18n as admin_i18n
    ADMIN_I18N_AVAILABLE = True
except ImportError:
    ADMIN_I18N_AVAILABLE = False


class GiswaterLogsI18n:
    """Internationalization handler for giswater_logs plugin"""

    def __init__(self, plugin_dir):
        self.plugin_dir = plugin_dir
        self.translations_dir = os.path.join(plugin_dir, 'translations')
        self._translations = {}
        self._load_translations()

    def _load_translations(self):
        for lang in ['es', 'ca', 'en', 'pt_BR']:
            translation_file = os.path.join(self.translations_dir, f'{lang}.json')
            if os.path.exists(translation_file):
                try:
                    with open(translation_file, 'r', encoding='utf-8') as f:
                        self._translations[lang] = json.load(f)
                except Exception as e:
                    print(f"Error loading translation file {lang}.json: {e}")

    def get_language(self):
        if hasattr(request, 'args') and request.args.get('lang'):
            return request.args.get('lang')

        if ADMIN_I18N_AVAILABLE:
            try:
                admin_lang = admin_i18n('interface.common.add')
                if admin_lang == 'Añadir':
                    return 'es'
                elif admin_lang == 'Afegir':
                    return 'ca'
                elif admin_lang == 'Add':
                    return 'en'
                elif admin_lang == 'Adicionar':
                    return 'pt_BR'
            except Exception:
                pass

        if hasattr(request, 'args') and request.args.get('lang') == 'pt':
            return 'pt_BR'

        if hasattr(request, 'headers'):
            accept_language = request.headers.get('Accept-Language', '').lower()
            if 'pt' in accept_language:
                return 'pt_BR'
            elif 'es' in accept_language and 'ca' not in accept_language:
                return 'es'
            elif 'ca' in accept_language:
                return 'ca'
            elif 'en' in accept_language:
                return 'en'

        return 'es'

    def translate(self, key, **kwargs):
        if ADMIN_I18N_AVAILABLE and key.startswith('interface.'):
            try:
                return admin_i18n(key, **kwargs)
            except Exception:
                pass

        lang = self.get_language()
        translations = self._translations.get(lang, self._translations.get('es', {}))
        text = translations.get(key, key)

        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):
                pass

        return text

    def __call__(self, key, **kwargs):
        return self.translate(key, **kwargs)


plugin_dir = os.path.dirname(os.path.abspath(__file__))
i18n = GiswaterLogsI18n(plugin_dir)
