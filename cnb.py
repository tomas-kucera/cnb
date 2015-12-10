# -*- coding: utf-8 -*-

"""Python lib to access exchange rates from the Czech National Bank.

Usage:
  import cnb
  from datetime import date, datetime, timedelta
  cnb.rate('USD')
    24.688
  cnb.convert(1000, 'USD')
    24688.0
  cnb.convert(1000, 'USD', 'HUF')
    287571.34
  cnb.convert_to('USD', 1000)
    40.5055
  cnb.worse(50, 'CZK', 5, 'PLN')   # 50 CZK given, 5 PLN obtained or paid
    (37.76, 18.88, 3.0334)         # -37.76 % = - 18.88 CZK = - 3 PLN
  today = date.today()
  monday = datetime.strptime('07.12.2015', '%d.%m.%Y').date()
  cnb.rate_tuple('USD')
    (24.688, 1.0, datetime.date(2015, 12, 9))
  cnb.rate_tuple('HUF', date=monday)
    (8.629, 100.0, datetime.date(2015, 12, 4))   # 07.12.2015, before 14:00, query made
    (8.629, 100.0, datetime.date(2015, 12, 4))   # 07.12.2015, before 14:00, from cache, see CACHE_YESTERDAY_BEFORE_HOUR
    (8.629, 100.0, datetime.date(2015, 12, 4))   # 07.12.2015, before 14:30, query made
    (8.666, 100.0, datetime.date(2015, 12, 7))   # 07.12.2015, after 14:30, query made
    (8.666, 100.0, datetime.date(2015, 12, 7))   # 07.12.2015, after 14:30, from cache
  cnb.rate('HUF', date=today - timedelta(days=359))
    0.08938
  cnb.convert(1000, 'USD', 'HUF', date=today - timedelta(days=359))
    248277.02
  cnb.monthly_rate('HUF', 2015, 3)
    9.024
  cnb.monthly('HUF', 2015, 3)
    0.09024

In fact this is fork of cnb-exchange-rate (stepansojka/cnb-exchange-rate, thx to Stepan Sojka),
  but not made as standard github fork, because of
    - change to the module (from package),
    - file renames,
    - changed import mechanism

Compare with cnb-exchange-rate:
  Focus of this fork is the work with current rate and (short time) historical daily rates.
  Basic method rate() (cnb-exchange-rate: daily_rate()) can be called without date to get current rate.
  Not published dates include today and future dates are provided (if older one date exists).
  Result of rate() is real rate (with regard to amount: 1,100,..).
  Today rates are cached for next use.
  convert(), convert_to() methods are added for exchange calculations.
  Bonus methods worse(), modified() for some dependend calculations
  Exceptions are not re-raised.
  Not focused methods from cnb-exchange-rate remains here, but probably there will be no development in the future.
  But for methods which seek for average were added their clones which take regard to currency amount:
            (monthly(), monthly_cumulative(), quarterly())
"""

import datetime
import csv

from pytz import timezone
from six.moves.urllib.request import urlopen

host = 'www.cnb.cz'

URL = 'http://%s/cs/financni_trhy/devizovy_trh/kurzy_devizoveho_trhu/prumerne_mena.txt?mena=%s'
DAILY_URL = 'http://%s/cs/financni_trhy/devizovy_trh/kurzy_devizoveho_trhu/vybrane.txt?mena=%s&od=%s&do=%s'
MONTHLY_AVERAGE_TABLE_IDX = 0
CUMULATIVE_MONTHLY_AVERAGE_TABLE_IDX = 1
QUARTERLY_AVERAGE_TABLE_IDX = 2
FIELD_DELIMITER = '|'
TABLE_DELIMITER = '\n\n'
TABLE_ENCODING = 'UTF-8'
DAYCNT = 8
CACHE_YESTERDAY_BEFORE = '14:00'  # dd:mm (CNB updates the service at 14:30)
SIZE_CACHE_OLDER = 500            # maximum items in cache (if more then only today rates will be appended)


# --- preferred methods

def rate(currency, date=None):
    """will return the rate for the currency today or for given date
    """
    result = _rate(currency, date)
    return apply_amount(result[0], result[1])

def rate_tuple(currency, date=None):
    """will return the rate for the reported amount of currency (today or for given date) as tuple:
    [0] rate for amount, [1] amount, [2] exact date from the data obtained from the service, [3] served from cache?
    """
    return _rate(currency, date)

def convert(amount, source, target='CZK', date=None, percent=0):
    """without target parameter returns equivalent of amount+source in CZK
    with target parameter returns equivalent of amount+source in given currency
    you can calculate with regard to (given) date
    you can add additional margin with percent parameter
    """
    if source.upper() == 'CZK':
        czk = amount
    else:
        czk = amount * rate(source, date)
    result = convert_to(target, czk, date)
    return modified(result, percent)

def convert_to(target, amount, date=None, percent=0):
    """will convert the amount in CZK into given currency (target)
    you can calculate with regard to (given) date
    you can add additional margin with percent parameter
    """
    if target.upper() == 'CZK':
        result = amount
    else:
        result = amount / rate(target, date)
    return modified(result, percent)

def worse(src_amount, src_currency, target_amount_obtained, target_currency, date=None):
    """will calculate a difference between the calculated target amount and the amount you give as src_amount
      if you will obtain target_amount_obtained instead
    returns a tuple: (percent, difference_src_currency, difference_target_currency)
    """
    calculated = convert(src_amount, src_currency, target=target_currency, date=date)
    worse = calculated - target_amount_obtained
    worse_src = convert(worse, target_currency, target=src_currency, date=date)
    if src_amount:
        return worse_src / src_amount * 100.0, worse_src, worse
    elif not target_amount_obtained:
        return 0.0, worse_src, worse
    else:
        return float('inf') if (target_amount_obtained < 0) else float('-inf'), worse_src, worse

def modified(number, percent):
    """return the amount (or any other number) with added margin given by percent parameter
    (result has type float)
    """
    if percent:
        return number * (100 + percent) / 100.
    else:
        return float(number)

# --- helping methods

def apply_amount(nrate, amount):
    if amount == 1.0:
        return nrate
    else:
        return nrate / amount

def _rate(currency, date, cache={}):
    currency = currency.upper()
    if currency == 'CZK':
        return 1.0, 1.0, datetime.date.today(), False

    def from_cache():
        return cached[0], cached[1], datetime.datetime.strptime(cache_key[:10], '%d.%m.%Y').date(), True

    cacheable_if_over = True
    if date is None:
        date_ask = datetime.date.today()
    elif date >= datetime.date.today():
        date_ask = min(date, datetime.date.today())
    else:
        date_ask = date
        cacheable_if_over = False
    date_end = date_ask.strftime('%d.%m.%Y')

    cache_key = date_end + currency
    cached = cache.get(cache_key)
    if cached:
        return from_cache()
    cache_yesterday = datetime.datetime.now(timezone('Europe/Prague')).strftime('%H:%M') < CACHE_YESTERDAY_BEFORE
    if cache_yesterday:
        yesterday = date_ask - datetime.timedelta(days=1)
        cache_key = yesterday.strftime('%d.%m.%Y') + currency
        cached = cache.get(cache_key)
        if cached:
            return from_cache()

    date_start = date_ask - datetime.timedelta(days=DAYCNT)
    date_start = date_start.strftime('%d.%m.%Y')
    url = DAILY_URL % (host, currency, date_start, date_end)
    t = download_table(url, 0)
    amount = float(t['Mna: %s' % currency][0].split()[-1])
    for test in xrange(DAYCNT + 1):
        date_test = date_ask - datetime.timedelta(days=test)
        key = date_test.strftime('%d.%m.%Y')
        if key in t:
            break
    else:
        raise ValueError('rate not found for currency %s (bad code, date too old, ..)' % currency)
    nrate = get_rate(t, key, 0)

    if cacheable_if_over or len(cache) < SIZE_CACHE_OLDER:
        cache[key + currency] = nrate, amount

    return nrate, amount, date_test, False

def download(url):
    stream = urlopen(url)
    raw = stream.read()

    return raw.decode('ascii', 'ignore')

def parse_table(table):
    csv_reader = csv.reader(table.split('\n'), delimiter=FIELD_DELIMITER)
    d = {}

    for row in csv_reader:
        if len(row) > 1:
            d[row[0]] = row[1:]

    return d

def download_table(url, table_index):
    tables = download(url).split(TABLE_DELIMITER)
    return parse_table(tables[table_index])

def get_rate(t, key, index):   # called rate() in cnb-exchange-rate
    s = t[str(key)][index]
    return float(s.replace(',','.'))

# --- other methods (without any change except of # **) from cnb-exchange-rate

def set_host(h):
    global host
    host = h

def average(currency, table_idx, year, value_idx):
    url = URL % (host, currency.upper())               # ** here changed to .upper()
    t = download_table(url, table_idx)
    return get_rate(t, year, value_idx - 1)

def monthly_rate(currency, year, month):
    return average(currency, MONTHLY_AVERAGE_TABLE_IDX, year, month)

def monthly_cumulative_rate(currency, year, month):
    return average(currency, CUMULATIVE_MONTHLY_AVERAGE_TABLE_IDX, year, month)

def quarterly_rate(currency, year, quarter):
    return average(currency, QUARTERLY_AVERAGE_TABLE_IDX, year, quarter)

def daily_rate(currency, date):
    date_str = date.strftime('%d.%m.%Y')
    url = DAILY_URL % (host, currency, date_str, date_str)
    t = download_table(url, 0)
    return get_rate(t, date_str, 0)

# --- modified methods from cnb-exchange-rate which will return the rate with regard to the amount
def monthly(currency, year, month):
    return apply_amount(monthly_rate(currency, year, month), rate_tuple(currency)[1])

def monthly_cumulative(currency, year, month):
    return apply_amount(monthly_cumulative_rate(currency, year, month), rate_tuple(currency)[1])

def quarterly(currency, year, quarter):
    return apply_amount(quarterly_rate(currency, year, quarter), rate_tuple(currency)[1])

daily = rate