"""Stable source URL identity for preparation, independent of legacy M01 code."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def norm_url(value: str) -> str:
    try:
        parsed = urlsplit((value or '').strip())
        if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname:
            return ''
        query = '' if parsed.hostname.lower() in {'topcv.vn', 'www.topcv.vn', 'itviec.com', 'www.itviec.com'} else urlencode(
            [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() not in {'fbclid', 'gclid'}])
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                           parsed.path.rstrip('/'), query, ''))
    except ValueError:
        return ''


def topcv_posting_id(value: str) -> str | None:
    try:
        parsed = urlsplit(value or '')
        if parsed.scheme.lower() not in {'http', 'https'} or (parsed.hostname or '').lower() not in {'topcv.vn', 'www.topcv.vn'}:
            return None
        match = re.fullmatch(r'/viec-lam/[^/]+/(\d+)\.html/?', parsed.path, flags=re.I)
        return match.group(1) if match else None
    except ValueError:
        return None
