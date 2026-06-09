import requests
codes = ['600000','600004','600006','600007','600008','600009','600010']
for c in codes:
    prefix = 'sh' if c.startswith('6') else 'sz'
    url = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{c},day,2026-01-01,,100,qfq'
    r = requests.get(url, timeout=10)
    data = r.json()
    key = prefix + c
    has_data = 'data' in data
    has_key = has_data and key in data.get('data', {})
    kl = None
    if has_key:
        kl = data['data'][key].get('qfqday') or data['data'][key].get('day')
    if kl is not None:
        print(f'{c}: OK len={len(kl)}')
    else:
        print(f'{c}: FAIL data_in={has_data} key_in={has_key}')
