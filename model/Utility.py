# standard libraries
import datetime
import time

# third party libraries
# None

# local libraries
# None


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format
# datetime_item is a dictionary with entries for the local_datetime, tz (timezone offset), and
# dst (daylight savings time offset). it may optionally include tz_name (timezone name), if available.
def get_datetime_item_from_datetime(datetime_):
    datetime_item = dict()
    datetime_item["local_datetime"] = datetime_.isoformat()
    tz_minutes = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) / 60
    datetime_item["tz"] = '{0:+03d}{1:02d}'.format(tz_minutes / 60, tz_minutes % 60)
    datetime_item["dst"] = "+60" if time.localtime().tm_isdst else "+00"
    return datetime_item


def get_current_datetime_item():
    return get_datetime_item_from_datetime(datetime.datetime.now())


# return python datetime object from a datetime_item. may return None if the datetime element is
# not properly formatted.
def get_datetime_from_datetime_item(datetime_item):
    if len(datetime_item["local_datetime"]) == 26:
        return datetime.datetime.strptime(datetime_item["local_datetime"], "%Y-%m-%dT%H:%M:%S.%f")
    elif len(datetime_item["local_datetime"]) == 19:
        return datetime.datetime.strptime(datetime_item["local_datetime"], "%Y-%m-%dT%H:%M:%S")
    return None


class Singleton(type):
    def __init__(cls, name, bases, dict):
        super(Singleton, cls).__init__(name, bases, dict)
        cls.instance = None

    def __call__(cls, *args, **kw):
        if cls.instance is None:
            cls.instance = super(Singleton, cls).__call__(*args, **kw)
        return cls.instance
