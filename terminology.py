"""Presentation-only Pepazo terminology, preserving persisted keys and game state."""
import re


_LEGACY_WORD = re.compile(
    r'\bcaparaz(?P<form>ones|[oó]n)\b(?P<optional>\(es\))?'
    r'(?:[ \t]+azul(?:es)?\b(?:\(es\))?)?', re.IGNORECASE)
_SYSTEM_FIELDS = {'desc', 'description', 'summary', 'error', 'retirementReason'}
_SYSTEM_EVENTS = {'SHELL_LAUNCHED', 'SHELL_SPUN', 'SHELL_RETURNED', 'CLIP_REWARD', 'PICKEM_REWARD',
                  'PENALTY_ADMIN_CORRECTION'}


def pepazo_text(value):
    """Translate legacy UI wording without changing identifiers or non-string values."""
    if not isinstance(value, str):
        return value
    def replace(match):
        word = 'pepazos' if match.group('form').casefold() == 'ones' else 'pepazo'
        if match.group('optional'):
            word += '(s)'
        if match.group().isupper():
            return word.upper()
        return word.capitalize() if match.group()[0].isupper() else word
    return _LEGACY_WORD.sub(replace, value)


def pepazo_payload(value, context=None):
    """Normalize generated labels on output, not user identities, votes, keys or storage."""
    if isinstance(value, list):
        return [pepazo_payload(item, context) for item in value]
    if not isinstance(value, dict):
        return value
    penalty = 'baseId' in value or value.get('id') == 'return_shell' or (
        context in ('penalty', 'result', 'penaltyCatalog') and 'name' in value and 'desc' in value)
    result = {}
    for key, item in value.items():
        normalized = pepazo_payload(item, key)
        if (key in _SYSTEM_FIELDS or (key == 'name' and penalty)
                or (key == 'title' and value.get('id') == 'first_individual_shell')
                or (key == 'message' and value.get('type') in _SYSTEM_EVENTS)):
            normalized = pepazo_text(normalized)
        result[key] = normalized
    return result
