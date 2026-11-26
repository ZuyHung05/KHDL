from __future__ import annotations

import logging
import re
import socket
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright, BrowserContext, Browser

from .config import load_crawler_config

LOGGER = logging.getLogger("it4930.crawlers.browser")

_CFG = load_crawler_config()
_BROWSER = _CFG.get("browser", {})

USER_AGENT = _BROWSER.get(
    "user_agent",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
)
_DEFAULT_FALLBACK_DNS = _BROWSER.get("fallback_dns", "10.36.255.51")
_STEALTH_INIT = _BROWSER.get(
    "stealth_init",
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "Object.defineProperty(navigator,'languages',{get:()=>['vi-VN','vi','en-US','en']});"
    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
    "window.chrome=window.chrome||{runtime:{}};",
)
_DEFAULT_VIEWPORT = {
    "width": _BROWSER.get("viewport", {}).get("width", 1280),
    "height": _BROWSER.get("viewport", {}).get("height", 900),
}
_LOCALE = _BROWSER.get("locale", "vi-VN")
_TIMEZONE_ID = _BROWSER.get("timezone_id", "Asia/Ho_Chi_Minh")


def _resolve_host(host: str, fallback_dns: str | None) -> str | None:
    try:
        ip = socket.gethostbyname(host)
        if ip:
            return ip
    except OSError:
        pass
    if not fallback_dns:
        return None
    try:
        out = subprocess.run(
            ["nslookup", host, fallback_dns],
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"Address\s*:\s*(\d+\.\d+\.\d+\.\d+)", out.stdout)
    return m.group(1) if m else None


def host_resolver_rules(hosts: list[str], fallback_dns: str | None = None) -> str:
    rules = []
    for host in hosts:
        ip = _resolve_host(host, fallback_dns)
        if ip:
            rules.append(f"MAP {host} {ip}")
    return ",".join(rules)


def _base_args(pin_hosts, fallback_dns, extra) -> list[str]:
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        *extra,
    ]
    rules = host_resolver_rules(pin_hosts or [], fallback_dns)
    if rules:
        args.append(f"--host-resolver-rules={rules}")
    return args


def _context_kwargs(headless: bool, viewport: dict, **kwargs) -> dict:
    return {
        "user_agent": kwargs.get("user_agent", USER_AGENT),
        "viewport": kwargs.get("viewport", viewport),
        "locale": kwargs.get("locale", _LOCALE),
        "timezone_id": kwargs.get("timezone_id", _TIMEZONE_ID),
    }


def _close(*objs) -> None:
    for obj in objs:
        if obj:
            try:
                obj.close()
            except Exception:  # noqa: BLE001 - cleanup best effort
                pass


@contextmanager
def playwright_page(profile_dir: str | Path, headless: bool = True,
                    hosts: list[str] | None = None,
                    fallback_dns: str | None = _DEFAULT_FALLBACK_DNS,
                    viewport: dict | None = None):
    profile = Path(profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    browser: Browser | None = None
    ctx: BrowserContext | None = None
    try:
        args = _base_args(hosts, fallback_dns, ["--disable-infobars"])
        browser = pw.chromium.launch(channel="chrome", headless=headless, args=args)
        ctx = browser.new_context(**_context_kwargs(headless, _DEFAULT_VIEWPORT if viewport is None else viewport))
        ctx.add_init_script(_STEALTH_INIT)
        page = ctx.new_page()
        yield pw, browser, ctx, page
    finally:
        _close(ctx, browser)
        pw.stop()


@contextmanager
def persistent_chromium(profile_dir: str | Path, headless: bool = True,
                        hosts: list[str] | None = None,
                        fallback_dns: str | None = _DEFAULT_FALLBACK_DNS,
                        **kwargs):
    profile = Path(profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    args = _base_args(hosts, fallback_dns, ["--disable-infobars"])
    width = kwargs.pop("width", _DEFAULT_VIEWPORT["width"])
    height = kwargs.pop("height", _DEFAULT_VIEWPORT["height"])
    pw = sync_playwright().start()
    browser = None
    try:
        browser = pw.chromium.launch_persistent_context(
            str(profile),
            channel="chrome",
            headless=headless,
            user_agent=kwargs.pop("user_agent", USER_AGENT),
            viewport={"width": width, "height": height},
            locale=kwargs.pop("locale", _LOCALE),
            timezone_id=kwargs.pop("timezone_id", _TIMEZONE_ID),
            args=args,
            **kwargs,
        )
        yield browser
    finally:
        _close(browser)
        pw.stop()


def webkit_context(profile_dir: str | Path, headless: bool = True, **kwargs):
    return persistent_chromium(profile_dir, headless=headless, **kwargs)
