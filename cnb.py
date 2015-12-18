# -*- coding: utf-8 -*-

"""Python lib to access exchange rates from the Czech National Bank.
Fork of (PyPI) cnb-exchange-rate (MIT licensed).
install_requires = ['six', 'pytz']

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
    (24.688, 1.0, datetime.date(2015, 12, 9), True, False)  # True: from cache because USD was used earlier
  cnb.rate_tuple('HUF', date=monday)
    (8.629, 100.0, datetime.date(2015, 12, 4), True, False)   # 07.12.2015, before 14:00, see CACHE_YESTERDAY_BEFORE_HOUR
    (8.629, 100.0, datetime.date(2015, 12, 4), False, False)  # 07.12.2015, before 14:30, query made
    (8.666, 100.0, datetime.date(2015, 12, 7), False, False)  # 07.12.2015, after 14:30, query made
    (8.666, 100.0, datetime.date(2015, 12, 7), True, False)  # 07.12.2015, after 14:30, from cache
  cnb.rate('HUF', date=today - timedelta(days=359))
    0.08938
  cnb.result_info('HUF')
    (8.938, 100.0, datetime.date(2014, 12, 15), False, False)
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
  Rates are cached for next use. Cache and file cache can help if CNB service is unavailable.
  With valid_max_days parameter you can set which cache results are valid if service call has failed.
  convert(), convert_to() methods are added for exchange calculations.
  Bonus methods worse(), modified() for some dependend calculations
  Exceptions are not re-raised (and not handled). In addition raises ValueError if rate cannot be found.
  Not focused methods from cnb-exchange-rate remains here, but probably there will be no development in the future.
  But for methods which seek for average were added their clones which take regard to currency amount:
            (monthly(), monthly_cumulative(), quarterly())
"""

import csv
import datetime
import json
import os
import tempfile

from pytz import timezone
from six.moves.urllib.request import urlopen
from six.moves import range


host = 'www.cnb.cz'

URL = 'http://%s/cs/financni_trhy/devizovy_trh/kurzy_devizoveho_trhu/prumerne_mena.txt?mena=%s'
DAILY_URL = 'http://%s/cs/financni_trhy/devizovy_trh/kurzy_devizoveho_trhu/vybrane.txt?mena=%s&od=%s&do=%s'
MONTHLY_AVERAGE_TABLE_IDX = 0
CUMULATIVE_MONTHLY_AVERAGE_TABLE_IDX = 1
QUARTERLY_AVERAGE_TABLE_IDX = 2
FIELD_DELIMITER = '|'
TABLE_DELIMITER = '\n\n'
TABLE_ENCODING = 'UTF-8'
DAYCNT = 8                        # how many days back we will ask the rate (CNB doesn't publish rates on weekends,..)
CACHE_YESTERDAY_BEFORE = '14:00'  # dd:mm (CNB updates the service at 14:30)
OFFLINE_CACHE = True              # if service call fails then try caches (memory, tmp/_cnb_cache_.json)
VALID_DAYS_MAX_DEFAULT = 60       # if service call fails, how many days different cache result is accepted as well
SIZE_CACHE_OLDER = 500            # maximum items in cache (if more then only today rates will be appended)

# do not change:
CACHE_FILENAME = None             # first _get_filename() call will set this
DATE_FORMAT = '%d.%m.%Y'          # used in URL and cache keys
RESULT_INFO = {}


# --- preferred methods

def rate(currency, date=None, valid_days_max=None):
    """will return the rate for the currency today or for given date
    valid_days_max is used only if service fails and this method try find something in cache
        dates from cache will be used in range <date - valid_days_max; date + valid_days_max>
        if valid_days_max is None (default), VALID_DAYS_MAX_DEFAULT is used instead
    """
    result = _rate(currency, date, valid_days_max=valid_days_max)
    return apply_amount(result[0], result[1])

def rate_tuple(currency, date=None, valid_days_max=None):
    """will return the rate for the reported amount of currency (today or for given date) as tuple:
    [0] rate for amount, [1] amount, [2] exact date from the data obtained from the service, [3] served from cache?,
        [4] True if service call was made but has failed
    valid_days_max: see rate()
    instead of use rate_tuple(currency,..) you can call rate(currency,..) and resolve result_info(currency) later
    """
    return _rate(currency, date, valid_days_max=valid_days_max)

def result_info(currency):
    """for previous call of rate(), rate_tuple(), convert(), convert_to() this will give same info tuple as rate_tuple()
    for worse() this works too, but because convert() is called twice, you will get bad info [3] served from cache?
    will return same result tuple as rate_tuple --or-- None if rate was not yet tested for the currency
    example: convert(10, 'usd', 'eur') ; result_info('eur')[2] # get real publishing date of the rate for EUR
    """
    return RESULT_INFO.get(currency.upper())

def convert(amount, source, target='CZK', date=None, percent=0, valid_days_max=None):
    """without target parameter returns equivalent of amount+source in CZK
    with target parameter returns equivalent of amount+source in given currency
    you can calculate with regard to (given) date
    you can add additional margin with percent parameter
    valid_days_max: see rate()
    """
    if source.upper() == 'CZK':
        czk = amount
    else:
        czk = amount * rate(source, date, valid_days_max=valid_days_max)
    result = convert_to(target, czk, date, valid_days_max=valid_days_max)
    return modified(result, percent)

def convert_to(target, amount, date=None, percent=0, valid_days_max=None):
    """will convert the amount in CZK into given currency (target)
    you can calculate with regard to (given) date
    you can add additional margin with percent parameter
    valid_days_max: see rate()
    """
    if target.upper() == 'CZK':
        result = amount
    else:
        result = amount / rate(target, date, valid_days_max=valid_days_max)
    return modified(result, percent)

def worse(src_amount, src_currency, target_amount_obtained, target_currency, date=None, valid_days_max=None):
    """will calculate a difference between the calculated target amount and the amount you give as src_amount
      if you will obtain target_amount_obtained instead
    valid_days_max: see rate()
    returns a tuple: (percent, difference_src_currency, difference_target_currency)
    """
    calculated = convert(src_amount, src_currency, target=target_currency, date=date, valid_days_max=valid_days_max)
    worse = calculated - target_amount_obtained
    worse_src = convert(worse, target_currency, target=src_currency, date=date, valid_days_max=valid_days_max)
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

def _rate(currency, date, valid_days_max=None, cache={}, fcache={}):
    currency = currency.upper()
    if valid_days_max is None:
        valid_days_max = VALID_DAYS_MAX_DEFAULT
    today = datetime.date.today()
    if currency == 'CZK':
        RESULT_INFO['CZK'] = result = (1.0, 1.0, today, False, False)
        return result

    def from_cache(failed=False):
        RESULT_INFO[currency] = result = (cached[0], cached[1],
                                        datetime.datetime.strptime(cache_key[:10], DATE_FORMAT).date(), True, failed)
        return result

    if date and date < today:
        date_ask = date
        fcacheable = False
    else:
        date_ask = today
        fcacheable = True

    cache_key = date_ask.strftime(DATE_FORMAT) + currency
    cached = cache.get(cache_key)
    if cached:
        return from_cache()
    cache_yesterday = datetime.datetime.now(timezone('Europe/Prague')).strftime('%H:%M') < CACHE_YESTERDAY_BEFORE
    if cache_yesterday:
        yesterday = date_ask - datetime.timedelta(days=1)
        cache_key = yesterday.strftime(DATE_FORMAT) + currency
        cached = cache.get(cache_key)
        if cached:
            return from_cache()

    date_start = date_ask - datetime.timedelta(days=DAYCNT)
    date_start = date_start.strftime(DATE_FORMAT)
    url = DAILY_URL % (host, currency, date_start, date_ask.strftime(DATE_FORMAT))
    try:
        t = download_table(url, 0)
        failed = False
    except IOError:
        failed = True

    if not failed:
        amount = float(t['Mna: %s' % currency][0].split()[-1])
        for test in range(DAYCNT + 1):
            date_test = date_ask - datetime.timedelta(days=test)
            key = date_test.strftime(DATE_FORMAT)
            if key in t:
                break
        else:
            failed = True

    if failed:
        if OFFLINE_CACHE:
            fcached = fcache.get(currency)
            try:
                if not fcached:     # try update it from file
                    with open(_get_filename()) as cache_file:
                        rf_cache = json.loads(cache_file.read())
                        for k in rf_cache:
                            if k not in fcache:
                                fcache[k] = rf_cache[k]
                    fcached = fcache.get(currency)
                if fcached:
                    fcache_date = datetime.datetime.strptime(fcached[2], DATE_FORMAT).date()
            except Exception:
                fcached = None
            test_delta = valid_days_max + 1
            if fcached:
                delta = abs((date_ask - fcache_date).days)
                if delta <= valid_days_max:
                    test_delta = delta
                else:
                    fcached = False
            # has memory cache any/better result?
            for delta_days in range(test_delta):   # TODO: how to make this faster and less stupid?
                tdelta = datetime.timedelta(days=delta_days)
                test_key = (today - tdelta).strftime(DATE_FORMAT) + currency
                cached = cache.get(test_key)
                if cached:
                    return from_cache(failed=True)
                if not delta_days:
                    continue
                test_key = (today + tdelta).strftime(DATE_FORMAT) + currency
                cached = cache.get(test_key)
                if cached:
                    return from_cache(failed=True)
            if fcached:
                RESULT_INFO[currency] = result = (fcached[0], fcached[1], fcache_date, True, True)
                return result
        raise ValueError('rate not found for currency %s (bad code, date too old, offline/not cached, ..)' % currency)

    nrate = get_rate(t, key, 0)
    if fcacheable or len(cache) < SIZE_CACHE_OLDER:
        cache[key + currency] = nrate, amount
        if fcacheable:
            fcache[currency] = nrate, amount, today.strftime(DATE_FORMAT)
            try:
                with open(_get_filename(), mode='w') as cache_file:
                    cache_file.write(json.dumps(fcache))
            except IOError:
                pass

    RESULT_INFO[currency] = result = (nrate, amount, date_test, False, False)
    return result

def _get_filename():
    global CACHE_FILENAME
    if not CACHE_FILENAME:
        CACHE_FILENAME = os.path.join(tempfile.gettempdir(), '_cnb_cache_.json')
    return CACHE_FILENAME

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
    date_str = date.strftime(DATE_FORMAT)              # ** '%d.%m.%Y' changed to DATE_FORMAT
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