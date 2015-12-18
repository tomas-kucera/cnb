# cnb
Python lib using exchange rates from the Czech National Bank. Based on cnb-exchange-rate but focus is the work with current rate and historical daily rates (500 days).

Status: Beta
0.9.2 fixed czk-lowercase; new: rate_tuple returns additional item 'served from cache?'
0.9.1 fixed FATAL: find rate before 14:30 (publishing in cnb); new: currencies allowed in lowercase too
0.9   published

Usage:
```
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
```

In fact this is fork of cnb-exchange-rate (stepansojka/cnb-exchange-rate, thx to Stepan Sojka),
but not made as standard github fork, because of
- change to the module (from package),
- file renames,
- changed import mechanism

Compare with cnb-exchange-rate:
- Focus of this fork is the work with current rate and (short time) historical daily rates.
- Basic method rate() (cnb-exchange-rate: daily_rate()) can be called without date to get current rate.
- Not published dates include today and future dates are provided (if older one date exists).
- Result of rate() is real rate (with regard to amount: 1,100,..).
- Rates are cached for next use. Cache and file cache can help if CNB service is unavailable.
- With valid_max_days parameter you can set which cache results are valid if service call has failed.
- convert(), convert_to() methods are added for exchange calculations.
- Bonus methods worse(), modified() for some dependend calculations
- Exceptions are not re-raised (and not handled). In addition raises ValueError if rate cannot be found.
- Not focused methods from cnb-exchange-rate remains here, but probably there will be no development in the future.
- But for methods which seek for average were added their clones which take regard to currency amount:
            (monthly(), monthly_cumulative(), quarterly())
