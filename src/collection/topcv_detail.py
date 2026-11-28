"""Extract TopCV detail text and detect challenge pages."""
from __future__ import annotations

from bs4 import BeautifulSoup


def get_description(soup: BeautifulSoup) -> dict[str, str]:
    boilerplate = ('Tiếp lợi thế', 'Hệ sinh thái HR Tech', 'TopCV hiểu rõ', 'Định vị bản thân')
    best = ''
    for element in soup.select('div, section'):
        text = element.get_text('\n', strip=True)
        if len(text) > 400 and not any(marker in text for marker in boilerplate) and len(text) > len(best):
            best = text
    if not best:
        raise RuntimeError('no description found')
    return {'description': best}


def is_cloudflare(soup: BeautifulSoup) -> bool:
    title = soup.title.get_text(' ', strip=True).lower() if soup.title else ''
    if any(marker in title for marker in ('just a moment', 'attention required', 'cloudflare')):
        return True
    if soup.select_one("#challenge-form, #cf-challenge-running, .cf-browser-verification, "
                       "#challenge-body-text, div.cf-wrapper, script[src*='challenges.cloudflare.com']"):
        return True
    snippet = soup.get_text(' ', strip=True)[:1500].lower()
    markers = ('checking your browser before accessing', 'cf-browser-verification',
               'enable javascript and cookies to continue', 'verify you are human',
               'performance & security by cloudflare', 'needs to review the security of your connection')
    return any(marker in snippet for marker in markers)
