import requests, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

codes = ['600000','600004','600006','600007','600008','600009','600010',
         '600011','600012','600015','600016','600017','600018','600019',
         '600020','600021','600022','600023','600025','600026','600027',
         '600028','600029','600030','600031','600032','600033','600035',
         '600036','600037']

def fetch(code):
    try:
        prefix = 'sh' if code.startswith('6') else 'sz'
        url = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,2026-01-01,,100,qfq'
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        key = prefix + code
        if 'data' not in data or key not in data['data']: return None
        kl = data['data'][key].get('qfqday') or data['data'][key].get('day')
        if not kl or len(kl) < 61: return None
        return kl
    except Exception as e:
        sys.stderr.write(f"ERR {code}: {type(e).__name__}: {e}\n")
        return None

print("Testing with 30 stocks via ThreadPoolExecutor...")
results = {}
with ThreadPoolExecutor(max_workers=10) as ex:
    fut_map = {ex.submit(fetch, c): c for c in codes}
    for fut in as_completed(fut_map):
        c = fut_map[fut]
        try:
            d = fut.result()
            if d: results[c] = len(d)
        except Exception as e:
            sys.stderr.write(f"FUT ERR {c}: {type(e).__name__}: {e}\n")

print(f"Success: {len(results)}/{len(codes)}")
for c, l in sorted(results.items()):
    print(f"  {c}: len={l}")
