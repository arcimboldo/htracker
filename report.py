#!/usr/bin/env python
# -*- coding: utf-8 -*-#
#
#
# Copyright (C) 2017, Centralway AG. All rights reserved.

__docformat__ = 'reStructuredText'
__author__ = 'Antonio Messina <antonio.messina@centralway.com>'

import pandas as pd
import calendar as cl
import argparse
from pandas.tseries.offsets import CustomBusinessDay
import sys
import unittest
import dateutil

# https://www.feiertagskalender.ch/index.php?geo=2872&klasse=3&jahr=2017&hl=en
CH_holidays = [
    '2017-01-01', # New years eve
    '2017-04-14', # Good Friday
    '2017-04-17', # Easter Monday
    '2017-05-01', # Labour Day
    '2017-05-25', # Ascension day
    '2017-06-05', # Whit Monday
    '2017-08-01', # Swiss National Holiday
    '2017-09-11', # Knabenschiessen
    '2017-12-25', # Christmas
]

CHHolidays = [pd.date_range(start=i, end=i) for i in CH_holidays]
CHCalendar = CustomBusinessDay(holidays=CHHolidays)

# 42 hours per week + 30 minutes for lunch
mlunch = 30
#mperday=60*42.0/5 + mlunch
mperday=60*42.0/5

def mtoh(n):
    return "%d:%02d" % (n/60, n%60)

def expected_to_work(month, year=2017):
    # how many minutes we should work on this month?
    bdays = pd.bdate_range('%d-%d-1' % (year, month),
                           '%d-%d-%d' % (year, month, cl.monthrange(year, month)[1]),
                           freq=CHCalendar)

    return (len(bdays), mperday*len(bdays))


def parsedate(line):
    tokens = line.split('-')
    s = dateutil.parser.parse(tokens[0], dayfirst=True)
    if len(tokens) > 1:
        e = dateutil.parser.parse(tokens[1], dayfirst=True)
        return pd.date_range(start=s, end=e)
    return [s]

class Test(unittest.TestCase):
    def test_parsedate(self):
        dt = pd.datetime
        for line, dates in [
                ("01/02/2017", [dt(2017,2,1)]),
                ("12.08.2017 - 15.08.2017", [dt(2017,8,12), dt(2017,8,13), dt(2017,8,14), dt(2017,8,15)]),
                ]:
            parsed = parsedate(line)
            self.assertEqual(len(parsed), len(dates))
            for i, d in enumerate(parsed):
                self.assertEqual(d, dates[i])

def setup():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", help="Filename")
    parser.add_argument("-f", "--full", action="store_true", help="Full report")
    parser.add_argument("-v", dest='vfile', required=True, help="File containing vacation days")
    cfg = parser.parse_args()
    vacations = []
    try:
        with open(cfg.vfile) as fd:
            for line in fd:
                if line.strip()[0] == '#':
                    continue
                vacations += parsedate(line)
        cfg.vacation = [d.strftime("%Y/%m/%d") for d in vacations if d.weekday() < 5]
    except Exception as ex:
        parser.error("Error while parsing file %s: %s", cfg.vfile, ex)
    return cfg

def produce_report(fname, vacation=[]):
    # "Job","Clocked In","Clocked Out","Duration","Comment","Breaks","Adjustments","Mileage"
    # "Centralway","03/04/2017 08:50","03/04/2017 18:35","9:45","","","",""
    df = pd.read_csv(fname, parse_dates=[0,1,2], usecols=[1,2,3,4], names=['start','end','duration', 'notes'], skiprows=1, dayfirst=True)

    df['notes'] = df.notes.fillna('')
    for vday in vacation:
        # Add vacation days as fully worked days
        start = pd.datetime.strptime(vday + ' 8:00', '%Y/%m/%d %H:%M')
        end = start + pd.DateOffset(minutes=mperday)
        t0 = pd.datetime.today()
        t = pd.datetime(t0.year, t0.month, t0.day) + pd.DateOffset(minutes=mperday)
        df = df.append({'start': start, 'end': end, 'duration': t, 'notes': "VACATION"}, ignore_index=True)

    df['day'] = df.start.apply(lambda d: d.date())
    df['m'] = df.duration.apply(lambda t: t.hour*60 + t.minute)
    df = df.sort_values(by='day').reindex()

    # Group by day to get rid of multiple clock-in in a given day
    df2 = df.groupby('day', as_index=False).m.sum()
    df2['month'] = df2.day.apply(lambda d: d.month)


    # FIXME 4 is hardcoded
    mnumber = 4
    month = df2[df2.month == mnumber]

    # Get the current year
    cyear, cmonth = month.day[0].year, month.day[0].month

    # working minutes per month:

    m = df2.groupby(df2.month, as_index=False).m.sum()

    # Now, for each remaining month, let's add some rows.
    for mn in range(m.month.max()+1, 13):
        m = m.append(
            {
                'month': mn,
                'm': 0,
            }, ignore_index=True)
    m['Month'] = m.month.apply(lambda x: cl.month_abbr[x])
    m['wdays'] = m.month.apply(lambda x: expected_to_work(x, year=cyear)[0])
    m['em'] = m.month.apply(lambda x: expected_to_work(x, year=cyear)[1])
    m['Total (h:m)'] = m.em.apply(lambda x: mtoh(x))
    m['Worked (h:m)'] = m.m.apply(lambda x: mtoh(x))
    m['balance_m'] = m['m'] - m['em']
    m['balance (h:m)'] = (m['m'] - m['em']).apply(lambda x: mtoh(x))
    m = m.rename(columns={"wdays": "Working days"})
    m = m.set_index(m.Month)

    return (m, df)


def main(cfg, stream=sys.stdout):
    m, full = produce_report(cfg.filename, cfg.vacation)

    stream.write("Running year\n")
    stream.write("Worked:          %9s\n" % mtoh(m.m.sum()))
    stream.write("Expected:        %9s\n" % mtoh(m.em.sum()))
    stream.write("Balance:         %9s\n" % mtoh(m.balance_m.sum()))
    stream.write("Vacation days:   %9d\n" % len(cfg.vacation))
    stream.write("\n")

    for label in ['m', 'em', 'month', 'Month', 'balance_m']:
        del m[label]
    # stream.write(df2)
    stream.write(m.to_string())
    stream.write("\n")

    if cfg.full:
        full['hours'] = full.m.apply(mtoh)
        full['month'] = full.day.apply(lambda x: x.strftime("%b"))
        full['day'] = full.day.apply(lambda x: x.strftime("%a %d"))

        full['start'] = full.start.apply(lambda x: x.strftime("%H:%M"))
        full['end'] = full.end.apply(lambda x: x.strftime("%H:%M"))

        full = full[['month', 'day', 'start', 'end', 'hours', 'notes']]
        stream.write("\n")
        stream.write("Full report\n")
        stream.write("-----------\n")
        stream.write(full.to_string(index=False))
        stream.write("\n")


if __name__ == "__main__":
    cfg = setup()
    
    main(cfg)
