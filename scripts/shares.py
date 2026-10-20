"""抓上市、上櫃公司已發行普通股數，存 config/shares.json（代號 → 股數），用來計算題材成分股市值。
資料來源：證交所 OpenAPI t187ap03_L、櫃買中心 OpenAPI mopsfe_t187ap03_O（公司基本資料）。
"""
import json, os, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = {
    'twse': 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L',
    'tpex': 'https://www.tpex.org.tw/openapi/v1/mopsfe_t187ap03_O',
}


def get(u):
    req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def pick(row, keys):
    for k in row:
        if any(s in k for s in keys):
            return row[k]
    return None


def num(x):
    try:
        return int(float(str(x).replace(',', '')))
    except Exception:
        return None


def main():
    out, notes = {}, []
    for name, u in SRC.items():
        rows = get(u)
        notes.append(f'{name} rows {len(rows)} fields {list(rows[0].keys()) if rows else []}')
        for r in rows:
            c = pick(r, ['公司代號', 'SecuritiesCompanyCode', 'CompanyCode'])
            s = num(pick(r, ['已發行普通股數', 'IssueShares', 'Shares']))
            if c and s:
                out[str(c).strip()] = s
    json.dump(out, open(f'{ROOT}/config/shares.json', 'w'), separators=(',', ':'), sort_keys=True)
    os.makedirs(f'{ROOT}/test', exist_ok=True)
    open(f'{ROOT}/test/shares_fields.txt', 'w', encoding='utf-8').write('\n'.join(notes) + f'\ncodes {len(out)}\n')
    print('\n'.join(notes), len(out))


if __name__ == '__main__':
    main()
