#!/usr/bin/env python3
"""Cache sector stocks - completely bypassing system proxy."""
import os, sys, json, time, warnings
warnings.filterwarnings("ignore")

# Clear proxy env vars
for k in list(os.environ.keys()):
    if 'proxy' in k.lower():
        del os.environ[k]
os.environ['no_proxy'] = '*'
os.environ['NO_PROXY'] = '*'

# Monkey-patch urllib3 proxy resolution BEFORE any HTTP imports
import urllib3.util.url
_orig_parse_url = urllib3.util.url.parse_url

# Patch ProxyManager to always resolve proxies as empty
import urllib3.poolmanager
_orig_proxy_from_url = urllib3.poolmanager.proxy_from_url
def patched_proxy_from_url(url, **kwargs):
    return None
urllib3.poolmanager.proxy_from_url = patched_proxy_from_url

# Also patch the get_environ_proxies in requests
import requests.utils
_orig_should_bypass = requests.utils.should_bypass_proxies
def always_bypass(url, no_proxy=None):
    return True
requests.utils.should_bypass_proxies = always_bypass

# Patch the getproxies_environment  
_orig_get_environ_proxies = requests.utils.get_environ_proxies
def no_proxies(url):
    return {}
requests.utils.get_environ_proxies = no_proxies

import akshare as ak

WORKDIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(WORKDIR)

print('Fetching concept names...', file=sys.stderr, flush=True)
concepts = ak.stock_board_concept_name_ths()
top = concepts.head(50)

cache = {}
success = 0
for i, (_, row) in enumerate(top.iterrows()):
    code = str(row['code'])
    name = str(row['name'])
    print(f'[{i+1}/50] {name} ... ', end='', file=sys.stderr, flush=True)
    try:
        cons = ak.stock_board_concept_cons_em(symbol=code)
        cols = list(cons.columns)
        ccol = next((c for c in cols if '代码' in str(c) or 'code' in str(c).lower()), None)
        ncol = next((c for c in cols if '名称' in str(c) or 'name' in str(c).lower()), None)
        if ccol and ncol:
            stocks = [{'code': str(r[ccol]), 'name': str(r[ncol])} for _, r in cons.iterrows()]
        elif len(cols) >= 2:
            stocks = [{'code': str(r[cols[0]]), 'name': str(r[cols[1]])} for _, r in cons.iterrows()]
        else:
            stocks = [{'code': '', 'name': str(r[cols[0]])} for _, r in cons.iterrows()]
        cache[name] = stocks
        success += 1
        print(f'{len(stocks)} stocks', file=sys.stderr)
    except Exception as e:
        cache[name] = []
        print(f'FAIL ({type(e).__name__})', file=sys.stderr)
    time.sleep(0.3)

os.makedirs('config', exist_ok=True)
with open('config/sector_stocks_cache.json', 'w', encoding='utf-8') as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)

print(f'\nDone: {success}/{len(cache)} sectors with stocks', file=sys.stderr)
print(json.dumps({'success': success, 'total': len(cache)}))
