import json
import os

class I18n:
    def __init__(self, locales_path="locales", default="en"):
        self.locales = {}
        self.default = default
        for fname in os.listdir(locales_path):
            if fname.endswith(".json"):
                lang = fname.split(".")[0]
                with open(os.path.join(locales_path, fname), "r", encoding="utf-8") as f:
                    self.locales[lang] = json.load(f)

    def t(self, key, lang=None, **kwargs):
        lang = lang or self.default
        data = self.locales.get(lang, self.locales.get(self.default, {}))
        s = data.get(key, key)
        try:
            return s.format(**kwargs)
        except Exception:
            return s