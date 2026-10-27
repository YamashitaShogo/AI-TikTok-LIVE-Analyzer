"""Read pywebview cookies in memory. Never log cookie values."""
from collections.abc import Mapping
from http.cookies import BaseCookie, Morsel


def extract_auth_cookies(cookies):
    values = {}
    def accept(name, value, domain=''):
        domain = str(domain or '').lower().lstrip('.')
        if domain and domain != 'tiktok.com' and not domain.endswith('.tiktok.com'):
            return
        if name in ('sessionid', 'tt-target-idc') and isinstance(value, str) and value.strip():
            values[name] = value
    def visit(cookie):
        if isinstance(cookie, Morsel):
            accept(cookie.key, cookie.value, cookie['domain'])
        elif isinstance(cookie, BaseCookie):
            for morsel in cookie.values(): visit(morsel)
        elif isinstance(cookie, Mapping):
            if 'name' in cookie and 'value' in cookie:
                accept(cookie['name'], cookie['value'], cookie.get('domain',''))
            else:
                for name,value in cookie.items():
                    if isinstance(value, Morsel): visit(value)
                    else: accept(name,value)
        else:
            accept(getattr(cookie,'name',None), getattr(cookie,'value',None), getattr(cookie,'domain',''))
    if isinstance(cookies, (Mapping, Morsel)):
        visit(cookies)
    else:
        for cookie in cookies or []: visit(cookie)
    return values.get('sessionid'), values.get('tt-target-idc')
