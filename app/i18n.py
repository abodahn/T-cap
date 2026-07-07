"""Trilingual-ready i18n. Ships English + Arabic (RTL). Dictionaries live in
static/i18n/<lang>.json. `t(key)` falls back to English, then the key itself."""
import json
from pathlib import Path

from flask import session, request

from config import Config

_DIR = Path(__file__).resolve().parent / "static" / "i18n"
_CACHE = {}


def _load(lang):
    if lang not in _CACHE:
        try:
            _CACHE[lang] = json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        except Exception:
            _CACHE[lang] = {}
    return _CACHE[lang]


def get_lang():
    lang = session.get("lang")
    if lang in Config.LANGUAGES:
        return lang
    # negotiate from Accept-Language, else default
    best = (request.accept_languages.best_match(Config.LANGUAGES)
            if request else None)
    return best or Config.DEFAULT_LANG


def is_rtl(lang=None):
    return (lang or get_lang()) == "ar"


def translate(key, **kw):
    lang = get_lang()
    val = _load(lang).get(key)
    if val is None and lang != "en":
        val = _load("en").get(key)
    if val is None:
        val = key
    if kw:
        try:
            val = val.format(**kw)
        except Exception:
            pass
    return val
