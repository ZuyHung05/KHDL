"""Pure title-alias classifier shared by baseline reports and frozen corpora."""
import re
import unicodedata


def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', str(text or '')).casefold().split())


def classify(title, taxonomy):
    text = normalized(title)
    matches = [(family, role) for family, roles in taxonomy.items() for role, aliases in roles.items()
               if any(re.search(r'(?<!\w)' + re.escape(normalized(alias)) + r'(?!\w)', text) for alias in aliases)]
    if len(matches) == 1:
        return 'classified', matches[0][0], matches[0][1]
    return ('needs_review' if matches else 'unknown'), None, None
