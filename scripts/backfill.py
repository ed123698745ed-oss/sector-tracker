"""歷史回補（GitHub Actions 接力用）。

  python3 backfill.py list IDX N PER   列出第 IDX 個工作（共 N 個）要抓的日期，每個工作 PER 天
  python3 backfill.py run YYYYMMDD,…   逐日抓取；原始檔存 archive/raw，精簡檔存 data/quotes，
                                       休市日記入 data/closed.txt；單日失敗只記錄，不中斷

回補範圍由 backfill/REQUEST 的第一行指定，例如：2023-01-01 2025-09-30
"""
import datetime, gzip, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quotes  # noqa: E402

ROOT = quotes.ROOT
RAW = os.path.join(ROOT, 'archive', 'raw')
CLOSED = os.path.join(ROOT, 'data', 'closed.txt')


def closed_days():
    return set(open(CLOSED).read().split()) if os.path.exists(CLOSED) else set()


def missing():
    a, b = open(os.path.join(ROOT, 'backfill', 'REQUEST')).read().split()[:2]
    d, end = datetime.date.fromisoformat(a), datetime.date.fromisoformat(b)
    have, shut, out = set(os.listdir(quotes.OUT)), closed_days(), []
    while d <= end:
        ds = d.strftime('%Y%m%d')
        if d.weekday() < 5 and f'{ds}.json' not in have and ds not in shut:
            out.append(ds)
        d += datetime.timedelta(days=1)
    return sorted(out, reverse=True)  # 由新到舊


def save_raw(src, ds, obj):
    os.makedirs(f'{RAW}/{src}', exist_ok=True)
    with gzip.open(f'{RAW}/{src}/{ds}.json.gz', 'wt', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))


def run(dates):
    ok = fail = 0
    for ds in dates:
        d = datetime.date(int(ds[:4]), int(ds[4:6]), int(ds[6:]))
        try:
            tw = quotes.get_json(f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ds}&type=ALLBUT0999&response=json')
            time.sleep(3)
            tp = quotes.get_json(f'https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={d.year}%2F{d.month:02d}%2F{d.day:02d}&type=EW&response=json')
            time.sleep(3)
            save_raw('twse', ds, tw)
            save_raw('tpex', ds, tp)
            if quotes.save(ds, tw, tp):
                print(ds, 'saved', flush=True)
            else:
                with open(CLOSED, 'a') as f:
                    f.write(ds + '\n')
                print(ds, 'closed', flush=True)
            ok += 1
        except BaseException as e:  # SystemExit 也只記錄
            fail += 1
            print(ds, 'FAILED', e, flush=True)
    print('done ok', ok, 'failed', fail)


if __name__ == '__main__':
    if sys.argv[1] == 'list':
        idx, n, per = map(int, sys.argv[2:5])
        print(','.join(missing()[idx * per:(idx + 1) * per]))
    elif sys.argv[1] == 'count':
        print(len(missing()))
    elif sys.argv[1] == 'run':
        run([x for x in sys.argv[2].split(',') if x])
