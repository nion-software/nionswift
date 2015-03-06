# standard libraries
import datetime
import logging
import time

# third party libraries
import numpy

# local libraries
# None


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format
# datetime_item is a dictionary with entries for the local_datetime, tz (timezone offset), and
# dst (daylight savings time offset). it may optionally include tz_name (timezone name), if available.
def get_datetime_item_from_datetime(datetime_local):
    datetime_item = dict()
    datetime_item["local_datetime"] = datetime_local.isoformat()
    tz_minutes = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) / 60
    datetime_item["tz"] = '{0:+03d}{1:02d}'.format(tz_minutes / 60, tz_minutes % 60)
    datetime_item["dst"] = "+60" if time.localtime().tm_isdst else "+00"
    return datetime_item


def get_current_datetime_item():
    return get_datetime_item_from_datetime(datetime.datetime.now())


def get_datetime_item_from_utc_datetime(datetime_utc):
    tz_minutes = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) / 60
    return get_datetime_item_from_datetime(datetime_utc + datetime.timedelta(minutes=tz_minutes))


# return python datetime object from a datetime_item. may return None if the datetime element is
# not properly formatted.
def get_datetime_from_datetime_item(datetime_item):
    local_datetime = datetime_item.get("local_datetime", str())
    if len(local_datetime) == 26:
        return datetime.datetime.strptime(local_datetime, "%Y-%m-%dT%H:%M:%S.%f")
    elif len(local_datetime) == 19:
        return datetime.datetime.strptime(local_datetime, "%Y-%m-%dT%H:%M:%S")
    return None


class Singleton(type):
    def __init__(cls, name, bases, dict):
        super(Singleton, cls).__init__(name, bases, dict)
        cls.instance = None

    def __call__(cls, *args, **kw):
        if cls.instance is None:
            cls.instance = super(Singleton, cls).__call__(*args, **kw)
        return cls.instance


def clean_dict(d0, clean_item_fn=None):
    """
        Return a json-clean dict. Will log info message for failures.
    """
    clean_item_fn = clean_item_fn if clean_item_fn else clean_item
    d = dict()
    for key in d0:
        cleaned_item = clean_item_fn(d0[key])
        if cleaned_item is not None:
            d[key] = cleaned_item
    return d


def clean_list(l0, clean_item_fn=None):
    """
        Return a json-clean list. Will log info message for failures.
    """
    clean_item_fn = clean_item_fn if clean_item_fn else clean_item
    l = list()
    for index, item in enumerate(l0):
        cleaned_item = clean_item_fn(item)
        if cleaned_item is None:
            logging.info("  in list at original index %s", index)
        else:
            l.append(cleaned_item)
    return l


def clean_tuple(t0, clean_item_fn=None):
    """
        Return a json-clean tuple. Will log info message for failures.
    """
    clean_item_fn = clean_item_fn if clean_item_fn else clean_item
    l = list()
    for index, item in enumerate(t0):
        cleaned_item = clean_item_fn(item)
        if cleaned_item is None:
            logging.info("  in tuple at original index %s", index)
        else:
            l.append(cleaned_item)
    return tuple(l)


def clean_item(i):
    """
        Return a json-clean item or None. Will log info message for failure.
    """
    itype = type(i)
    if itype == dict:
        return clean_dict(i)
    elif itype == list:
        return clean_list(i)
    elif itype == tuple:
        return clean_tuple(i)
    elif itype == numpy.float32:
        return float(i)
    elif itype == numpy.float64:
        return float(i)
    elif itype == float:
        return i
    elif itype == str or itype == unicode:
        return i
    elif itype == int or itype == long:
        return i
    elif itype == bool:
        return i
    elif itype == type(None):
        return i
    logging.info("Unable to handle type %s", itype)
    return None


def clean_item_no_list(i):
    """
        Return a json-clean item or None. Will log info message for failure.
    """
    itype = type(i)
    if itype == dict:
        return clean_dict(i, clean_item_no_list)
    elif itype == list:
        return clean_tuple(i, clean_item_no_list)
    elif itype == tuple:
        return clean_tuple(i, clean_item_no_list)
    elif itype == numpy.float32:
        return float(i)
    elif itype == numpy.float64:
        return float(i)
    elif itype == float:
        return i
    elif itype == str or itype == unicode:
        return i
    elif itype == int or itype == long:
        return i
    elif itype == bool:
        return i
    elif itype == type(None):
        return i
    logging.info("Unable to handle type %s", itype)
    return None


def parse_version(version, count=3):
    version_components = [int(version_component) for version_component in version.split(".")]
    assert len(version_components) <= count
    while len(version_components) < count:
        version_components.append(0)
    return version_components


def compare_versions(version1, version2):
    version_components1 = parse_version(version1)
    version_components2 = parse_version(version2)
    for version_component1, version_component2 in zip(version_components1, version_components2):
        if version_component1 > version_component2:
            return 1
        elif version_component1 < version_component2:
            return -1
    return 0
