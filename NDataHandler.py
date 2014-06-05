import binascii
import calendar
import datetime
import json
import numpy
import numpy.lib.format
import os
import StringIO
import struct
import time
import uuid

from nion.swift.model import Storage

# http://en.wikipedia.org/wiki/Zip_(file_format)
# http://www.pkware.com/documents/casestudies/APPNOTE.TXT
# https://issues.apache.org/jira/browse/COMPRESS-210
# http://proger.i-forge.net/MS-DOS_date_and_time_format/OFz

def npy_len_and_crc32(data):
    header = StringIO.StringIO()
    header.write(numpy.lib.format.magic(1, 0))
    numpy.lib.format.write_array_header_1_0(header, numpy.lib.format.header_data_from_array_1_0(data))
    data_len = len(header.getvalue()) + len(data.data)
    crc32 = binascii.crc32(data.data, binascii.crc32(header.getvalue())) & 0xFFFFFFFF
    return data_len, crc32

def write_data(fp, name, writer, data_len, crc32, dt):
    fp.write(struct.pack('I', 0x04034b50))  # local file header
    fp.write(struct.pack('H', 10))          # extract version (default)
    fp.write(struct.pack('H', 0))           # general purpose bits
    fp.write(struct.pack('H', 0))           # compression method
    msdos_date = int(dt.year - 1980) << 9 | int(dt.month) << 5 | int(dt.day)
    msdos_time = int(dt.hour) << 11 | int(dt.minute) << 5 | int(dt.second)
    fp.write(struct.pack('H', msdos_time))  # extract version (default)
    fp.write(struct.pack('H', msdos_date))  # extract version (default)
    fp.write(struct.pack('I', crc32))       # crc32
    fp.write(struct.pack('I', data_len))    # compressed length
    fp.write(struct.pack('I', data_len))    # uncompressed length
    fp.write(struct.pack('H', len(name)))   # name length
    fp.write(struct.pack('H', 0))           # extra length
    fp.write(name)
    writer(fp)

def write_directory_data(fp, offset, name, data_len, crc32, dt):
    fp.write(struct.pack('I', 0x02014b50))  # central directory header
    fp.write(struct.pack('H', 10))          # made by version (default)
    fp.write(struct.pack('H', 10))          # extract version (default)
    fp.write(struct.pack('H', 0))           # general purpose bits
    fp.write(struct.pack('H', 0))           # compression method
    msdos_date = int(dt.year - 1980) << 9 | int(dt.month) << 5 | int(dt.day)
    msdos_time = int(dt.hour) << 11 | int(dt.minute) << 5 | int(dt.second)
    fp.write(struct.pack('H', msdos_time))  # extract version (default)
    fp.write(struct.pack('H', msdos_date))  # extract version (default)
    fp.write(struct.pack('I', crc32))       # crc32
    fp.write(struct.pack('I', data_len))    # compressed length
    fp.write(struct.pack('I', data_len))    # uncompressed length
    fp.write(struct.pack('H', len(name)))   # name length
    fp.write(struct.pack('H', 0))           # extra length
    fp.write(struct.pack('H', 0))           # comments length
    fp.write(struct.pack('H', 0))           # disk number
    fp.write(struct.pack('H', 0))           # internal file attributes
    fp.write(struct.pack('I', 0))           # external file attributes
    fp.write(struct.pack('I', offset))      # relative offset of file header
    fp.write(name)

def write_end_of_directory(fp, dir_size, dir_offset, count):
    fp.write(struct.pack('I', 0x06054b50))  # central directory header
    fp.write(struct.pack('H', 0))           # disk number
    fp.write(struct.pack('H', 0))           # disk number
    fp.write(struct.pack('H', count))       # number of files
    fp.write(struct.pack('H', count))       # number of files
    fp.write(struct.pack('I', dir_size))    # central directory size
    fp.write(struct.pack('I', dir_offset))  # central directory offset
    fp.write(struct.pack('H', 0))           # comment len

def write_zip_fp(fp, data, properties, dir_data_list=None):
    # dir_data_list has the format: local file record offset, name, data length, crc32
    dir_data_list = list() if dir_data_list is None else dir_data_list
    dt = datetime.datetime.now()
    if data is not None:
        offset_data = fp.tell()
        data_len, crc32 = npy_len_and_crc32(data)
        writer = lambda fp: numpy.save(fp, data)
        write_data(fp, "data.npy", writer, data_len, crc32, dt)
        dir_data_list.append((offset_data, "data.npy", data_len, crc32))
    if properties is not None:
        json_io = StringIO.StringIO()
        json.dump(properties, json_io)
        json_str = json_io.getvalue()
        json_len = len(json_str)
        json_crc32 = binascii.crc32(json_str) & 0xFFFFFFFF
        writer = lambda fp: fp.write(json_str)
        offset_json = fp.tell()
        write_data(fp, "metadata.json", writer, json_len, json_crc32, dt)
        dir_data_list.append((offset_json, "metadata.json", json_len, json_crc32))
    dir_offset = fp.tell()
    for offset, name, data_len, crc32 in dir_data_list:
        write_directory_data(fp, offset, name, data_len, crc32, dt)
    dir_size = fp.tell() - dir_offset
    write_end_of_directory(fp, dir_size, dir_offset, len(dir_data_list))
    fp.truncate()

def write_zip(file_path, data, properties):
    with open(file_path, "wb") as fp:
        write_zip_fp(fp, data, properties)

def parse_zip(fp):
    local_files = {}
    dir_files = {}
    fp.seek(0)
    while True:
        pos = fp.tell()
        signature = struct.unpack('I', fp.read(4))[0]
        if signature == 0x04034b50:
            fp.seek(pos + 14)
            crc32 = struct.unpack('I', fp.read(4))[0]
            fp.seek(pos + 18)
            data_len = struct.unpack('I', fp.read(4))[0]
            fp.seek(pos + 26)
            name_len = struct.unpack('H', fp.read(2))[0]
            extra_len = struct.unpack('H', fp.read(2))[0]
            name = fp.read(name_len)
            fp.seek(extra_len, os.SEEK_CUR)
            data_pos = fp.tell()
            fp.seek(data_len, os.SEEK_CUR)
            local_files[pos] = (name, data_pos, data_len, crc32)
        elif signature == 0x02014b50:
            fp.seek(pos + 28)
            name_len = struct.unpack('H', fp.read(2))[0]
            extra_len = struct.unpack('H', fp.read(2))[0]
            comment_len = struct.unpack('H', fp.read(2))[0]
            fp.seek(pos + 42)
            pos2 = struct.unpack('I', fp.read(4))[0]
            name = fp.read(name_len)
            fp.seek(pos + 46 + name_len + extra_len + comment_len)
            dir_files[name] = (pos, pos2)
        elif signature == 0x06054b50:
            fp.seek(pos + 16)
            pos2 = struct.unpack('I', fp.read(4))[0]
            eocd = (pos, pos2)
            break
    return local_files, dir_files, eocd

def read_data(fp, local_files, dir_files, name):
    if name in dir_files:
        fp.seek(local_files[dir_files[name][1]][1])
        return numpy.load(fp)
    return None

def read_json(fp, local_files, dir_files, name):
    if name in dir_files:
        json_pos = local_files[dir_files[name][1]][1]
        json_len = local_files[dir_files[name][1]][2]
        fp.seek(json_pos)
        json_properties = fp.read(json_len)
        return json.loads(json_properties)
    return None

def rewrite_zip(file_path, properties):
    with open(file_path, "r+b") as fp:
        local_files, dir_files, eocd = parse_zip(fp)
        # check to make sure directory has two files, named data.npy and metadata.json, and that data.npy is first
        # TODO: check compression, etc.
        if len(dir_files) == 2 and "data.npy" in dir_files and "metadata.json" in dir_files and dir_files["data.npy"][1] == 0:
            fp.seek(dir_files["metadata.json"][1])
            dir_data_list = list()
            local_file_pos = dir_files["data.npy"][1]
            local_file = local_files[local_file_pos]
            dir_data_list.append((local_file_pos, "data.npy", local_file[2], local_file[3]))
            write_zip_fp(fp, None, properties, dir_data_list)
        else:
            data = None
            if "data.npy" in dir_files:
                fp.seek(local_files[dir_files["data.npy"][1]][1])
                data = numpy.load(fp)
            fp.seek(0)
            write_zip_fp(fp, data, properties)

#d = numpy.zeros((16, ), dtype=numpy.double)
#d[:] = numpy.linspace(0, 1, 16)

#write_zip("test.zip", d, {"abc": 4, "def": "string"})

#rewrite_zip("test.zip", {"abc": 5, "def": "string2"})



class NData2Handler(object):

    def __init__(self, data_dir):
        self.__data_dir = data_dir

    def get_reference(self, file_path):
        relative_file = os.path.relpath(file_path, self.__data_dir)
        return os.path.splitext(relative_file)[0]

    def is_matching(self, filename):
        return filename.endswith(".ndata2")

    def write_data(self, reference, data, file_datetime):
        assert data is not None
        data_file_path = reference + ".ndata2"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        #logging.debug("WRITE data file %s for %s", absolute_file_path, key)
        Storage.db_make_directory_if_needed(os.path.dirname(absolute_file_path))
        item_uuid, properties = self.read_properties(reference) if os.path.exists(absolute_file_path) else dict()
        with open(absolute_file_path, "wb") as fp:
            numpy.save(fp, data)
            pos = fp.tell()
            json.dump(properties, fp)
            fp.write(struct.pack('q', pos))
        # convert to utc time. this is temporary until datetime is cleaned up (again) and we can get utc directly from datetime.
        timestamp = calendar.timegm(file_datetime.timetuple()) + (datetime.datetime.utcnow() - datetime.datetime.now()).total_seconds()
        os.utime(absolute_file_path, (time.time(), timestamp))

    def write_properties(self, reference, properties, file_datetime):
        data_file_path = reference + ".ndata2"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        #logging.debug("WRITE properties %s for %s", absolute_file_path, key)
        Storage.db_make_directory_if_needed(os.path.dirname(absolute_file_path))
        exists = os.path.exists(absolute_file_path)
        mode = "r+b" if exists else "w+b"
        with open(absolute_file_path, mode) as fp:
            if exists:
                fp.seek(-8, os.SEEK_END)
                pos = struct.unpack('q', fp.read(8))[0]
            else:
                pos = 0
            fp.seek(pos)
            json.dump(properties, fp)
            fp.write(struct.pack('q', pos))
            fp.truncate()
        # convert to utc time. this is temporary until datetime is cleaned up (again) and we can get utc directly from datetime.
        timestamp = calendar.timegm(file_datetime.timetuple()) + (datetime.datetime.utcnow() - datetime.datetime.now()).total_seconds()
        os.utime(absolute_file_path, (time.time(), timestamp))

    def read_properties(self, reference):
        data_file_path = reference + ".ndata2"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        with open(absolute_file_path, "rb") as fp:
            fp.seek(-8, os.SEEK_END)
            pos_end = fp.tell()
            pos = struct.unpack('q', fp.read(8))[0]
            fp.seek(pos)
            json_properties = fp.read(pos_end - pos)
            properties = json.loads(json_properties)
        item_uuid = uuid.UUID(properties["uuid"])
        return item_uuid, properties

    def read_data(self, reference):
        data_file_path = reference + ".ndata2"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        #logging.debug("READ data file %s", absolute_file_path)
        with open(absolute_file_path, "rb") as fp:
            fp.seek(-8, os.SEEK_END)
            pos = struct.unpack('q', fp.read(8))[0]
            if pos > 0:
                fp.seek(0)
                return numpy.load(fp)
            return None
        return None

    def remove(self, reference):
        for suffix in ["ndata2"]:
            data_file_path = reference + "." + suffix
            absolute_file_path = os.path.join(self.__data_dir, data_file_path)
            #logging.debug("DELETE data file %s", absolute_file_path)
            if os.path.isfile(absolute_file_path):
                os.remove(absolute_file_path)


class NDataHandler(object):

    def __init__(self, data_dir):
        self.__data_dir = data_dir

    def get_reference(self, file_path):
        relative_file = os.path.relpath(file_path, self.__data_dir)
        return os.path.splitext(relative_file)[0]

    def is_matching(self, filename):
        return filename.endswith(".ndata")

    def write_data(self, reference, data, file_datetime):
        assert data is not None
        data_file_path = reference + ".ndata"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        #logging.debug("WRITE data file %s for %s", absolute_file_path, key)
        Storage.db_make_directory_if_needed(os.path.dirname(absolute_file_path))
        item_uuid, properties = self.read_properties(reference) if os.path.exists(absolute_file_path) else dict()
        write_zip(absolute_file_path, data, properties)
        # convert to utc time. this is temporary until datetime is cleaned up (again) and we can get utc directly from datetime.
        timestamp = calendar.timegm(file_datetime.timetuple()) + (datetime.datetime.utcnow() - datetime.datetime.now()).total_seconds()
        os.utime(absolute_file_path, (time.time(), timestamp))

    def write_properties(self, reference, properties, file_datetime):
        data_file_path = reference + ".ndata"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        #logging.debug("WRITE properties %s for %s", absolute_file_path, key)
        Storage.db_make_directory_if_needed(os.path.dirname(absolute_file_path))
        exists = os.path.exists(absolute_file_path)
        if exists:
            rewrite_zip(absolute_file_path, properties)
        else:
            write_zip(absolute_file_path, None, properties)
        # convert to utc time. this is temporary until datetime is cleaned up (again) and we can get utc directly from datetime.
        timestamp = calendar.timegm(file_datetime.timetuple()) + (datetime.datetime.utcnow() - datetime.datetime.now()).total_seconds()
        os.utime(absolute_file_path, (time.time(), timestamp))

    def read_properties(self, reference):
        data_file_path = reference + ".ndata"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        with open(absolute_file_path, "rb") as fp:
            local_files, dir_files, eocd = parse_zip(fp)
            properties = read_json(fp, local_files, dir_files, "metadata.json")
        item_uuid = uuid.UUID(properties["uuid"])
        return item_uuid, properties

    def read_data(self, reference):
        data_file_path = reference + ".ndata"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        #logging.debug("READ data file %s", absolute_file_path)
        with open(absolute_file_path, "rb") as fp:
            local_files, dir_files, eocd = parse_zip(fp)
            return read_data(fp, local_files, dir_files, "data.npy")
        return None

    def remove(self, reference):
        for suffix in ["ndata"]:
            data_file_path = reference + "." + suffix
            absolute_file_path = os.path.join(self.__data_dir, data_file_path)
            #logging.debug("DELETE data file %s", absolute_file_path)
            if os.path.isfile(absolute_file_path):
                os.remove(absolute_file_path)


def clean_dict(d):
    for key in d:
        d[key] = clean_item(d[key])
    return d


def clean_list(l):
    for index, item in enumerate(l):
        l[index] = clean_item(item)
    return l


def clean_tuple(t):
    l = []
    for item in t:
        l.append(clean_item(item))
    return tuple(l)


def clean_item(i):
    if type(i) == dict:
        return clean_dict(i)
    elif type(i) == list:
        return clean_list(i)
    elif type(i) == tuple:
        return clean_tuple(i)
    elif type(i) == numpy.float32:
        return float(i)
    return i
