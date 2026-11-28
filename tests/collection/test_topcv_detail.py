from bs4 import BeautifulSoup

from src.collection.topcv_detail import get_description, is_cloudflare


def test_topcv_detail_extracts_long_jd_and_rejects_challenge():
    jd = '<section><h2>Mô tả công việc</h2><p>' + 'Xây dựng API bằng Python. '*30 + '</p></section>'
    soup = BeautifulSoup('<html><title>Cloud Engineer</title><body>'+jd+'</body></html>', 'lxml')
    assert 'Xây dựng API' in get_description(soup)['description']
    assert not is_cloudflare(soup)

    blocked = BeautifulSoup('<html><title>Just a moment...</title><body>Checking</body></html>', 'lxml')
    assert is_cloudflare(blocked)
