# standard libraries
import datetime
import logging
import time

# third party libraries
# None

# local libraries
# None


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format
# datetime_element is a dictionary with entries for the local_datetime, tz (timezone offset), and
# dst (daylight savings time offset). it may optionally include tz_name (timezone name), if available.
def get_current_datetime_element():
    datetime_element = dict()
    datetime_element["local_datetime"] = datetime.datetime.now().isoformat()
    tz_minutes = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) / 60
    datetime_element["tz"] = '{0:+03d}{1:02d}'.format(tz_minutes/60, tz_minutes%60)
    datetime_element["dst"] = "+60" if time.localtime().tm_isdst else "+00"
    return datetime_element

# return python datetime object from a datetime_element. may return None if the datetime element is
# not properly formatted.
def get_datetime_from_datetime_element(datetime_element):
    if len(datetime_element["local_datetime"]) == 26:
        return datetime.datetime.strptime(datetime_element["local_datetime"], "%Y-%m-%dT%H:%M:%S.%f")
    elif len(datetime_element["local_datetime"]) == 19:
        return datetime.datetime.strptime(datetime_element["local_datetime"], "%Y-%m-%dT%H:%M:%S")
    return None
