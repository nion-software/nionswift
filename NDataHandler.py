"""
    A module for handle .ndata files for Swift.
"""

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

# http://en.wikipedia.org/wiki/Zip_(file_format)
# http://www.pkware.com/documents/casestudies/APPNOTE.TXT
# https://issues.apache.org/jira/browse/COMPRESS-210
# http://proger.i-forge.net/MS-DOS_date_and_time_format/OFz


def make_directory_if_needed(directory_path):
    """
        Make the directory path, if needed.
    """
    if os.path.exists(directory_path):
        if not os.path.isdir(directory_path):
            raise OSError("Path is not a directory:", directory_path)
    else:
        os.makedirs(directory_path)


def npy_len_and_crc32(data):
    """
        Calculate the length and crc32 for a npy file.

        Uses internal npy format routines to write the magic header to a string
        and then uses binascii to calculate the remaining checksum on the data.

        :param data: the numpy data array to checksum.
    """
    header = StringIO.StringIO()
    header.write(numpy.lib.format.magic(1, 0))
    numpy.lib.format.write_array_header_1_0(header, numpy.lib.format.header_data_from_array_1_0(data))
    data_len = len(header.getvalue()) + len(data.data)
    crc32 = binascii.crc32(data.data, binascii.crc32(header.getvalue())) & 0xFFFFFFFF
    return data_len, crc32


def write_local_file(fp, name, writer, data_len, crc32, dt):
    """
        Writes a zip file local file header structure at the current file position

        :param fp: the file point to which to write the header
        :param name: the name of the file
        :param writer: a function taking an fp parameter to do the writing
        :param data_len: the length of data that will be written to the archive
        :param crc32: the crc32 of the data to be written
        :param dt: the datetime to write to the archive
    """
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
    """
        Write a zip fie directory entry at the current file position

        :param fp: the file point to which to write the header
        :param offset: the offset of the associated local file header
        :param name: the name of the file
        :param data_len: the length of data that will be written to the archive
        :param crc32: the crc32 of the data to be written
        :param dt: the datetime to write to the archive
    """
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
    """
        Write zip file end of directory header at the current file position

        :param fp: the file point to which to write the header
        :param dir_size: the total size of the directory
        :param dir_offset: the start of the first directory header
        :param count: the count of files
    """
    fp.write(struct.pack('I', 0x06054b50))  # central directory header
    fp.write(struct.pack('H', 0))           # disk number
    fp.write(struct.pack('H', 0))           # disk number
    fp.write(struct.pack('H', count))       # number of files
    fp.write(struct.pack('H', count))       # number of files
    fp.write(struct.pack('I', dir_size))    # central directory size
    fp.write(struct.pack('I', dir_offset))  # central directory offset
    fp.write(struct.pack('H', 0))           # comment len


def write_zip_fp(fp, data, properties, dir_data_list=None):
    """
        Write custom zip file of data and properties to fp

        :param fp: the file point to which to write the header
        :param data: the data to write to the file; may be None
        :param properties: the properties to write to the file; may be None
        :param dir_data_list: optional list of directory header information structures

        If dir_data_list is specified, data should be None and properties should
        be specified. Then the existing data structure will be left alone and only
        the directory headers and end of directory header will be written.

        Otherwise, if both data and properties are specified, both are written
        out in full.
    """
    # dir_data_list has the format: local file record offset, name, data length, crc32
    dir_data_list = list() if dir_data_list is None else dir_data_list
    dt = datetime.datetime.now()
    if data is not None:
        offset_data = fp.tell()
        data_len, crc32 = npy_len_and_crc32(data)
        writer = lambda fp: numpy.save(fp, data)
        write_local_file(fp, "data.npy", writer, data_len, crc32, dt)
        dir_data_list.append((offset_data, "data.npy", data_len, crc32))
    if properties is not None:
        json_io = StringIO.StringIO()
        json.dump(properties, json_io)
        json_str = json_io.getvalue()
        json_len = len(json_str)
        json_crc32 = binascii.crc32(json_str) & 0xFFFFFFFF
        writer = lambda fp: fp.write(json_str)
        offset_json = fp.tell()
        write_local_file(fp, "metadata.json", writer, json_len, json_crc32, dt)
        dir_data_list.append((offset_json, "metadata.json", json_len, json_crc32))
    dir_offset = fp.tell()
    for offset, name, data_len, crc32 in dir_data_list:
        write_directory_data(fp, offset, name, data_len, crc32, dt)
    dir_size = fp.tell() - dir_offset
    write_end_of_directory(fp, dir_size, dir_offset, len(dir_data_list))
    fp.truncate()


def write_zip(file_path, data, properties):
    """
        Write custom zip file to the file path

        :param file_path: the file to which to write the zip file
        :param data: the data to write to the file; may be None
        :param properties: the properties to write to the file; may be None

        See write_zip_fp.
    """
    with open(file_path, "wb") as fp:
        write_zip_fp(fp, data, properties)


def parse_zip(fp):
    """
        Parse the zip file headers at fp

        :param fp: the file pointer from which to parse the zip file
        :return: A tuple of local files, directory headers, and end of central directory

        The local files are dictionary where the keys are the local file offset and the
        values are each a tuple consisting of the name, data position, data length, and crc32.

        The directory headers are a dictionary where the keys are the names of the files
        and the values are a tuple consisting of the directory header position, and the
        associated local file position.

        The end of central directory is a tuple consisting of the location of the end of
        central directory header and the location of the first directory header.

        This method will seek to location 0 of fp and leave fp at end of file.
    """
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
    """
        Read a numpy data array from the zip file

        :param fp: a file pointer
        :param local_files: the local files structure
        :param dir_files: the directory headers
        :param name: the name of the data file to read
        :return: the numpy data array, if found

        The file pointer will be at a location following the
        local file entry after this method.

        The local_files and dir_files should be passed from
        the results of parse_zip.
    """
    if name in dir_files:
        fp.seek(local_files[dir_files[name][1]][1])
        return numpy.load(fp)
    return None


def read_json(fp, local_files, dir_files, name):
    """
        Read json properties from the zip file

        :param fp: a file pointer
        :param local_files: the local files structure
        :param dir_files: the directory headers
        :param name: the name of the json file to read
        :return: the json properites as a dictionary, if found

        The file pointer will be at a location following the
        local file entry after this method.

        The local_files and dir_files should be passed from
        the results of parse_zip.
    """
    if name in dir_files:
        json_pos = local_files[dir_files[name][1]][1]
        json_len = local_files[dir_files[name][1]][2]
        fp.seek(json_pos)
        json_properties = fp.read(json_len)
        return json.loads(json_properties)
    return None


def rewrite_zip(file_path, properties):
    """
        Rewrite the json properties in the zip file

        :param file_path: the file path to the zip file
        :param properties: the updated properties to write to the zip file

        This method will attempt to keep the data file within the zip
        file intact without rewriting it. However, if the data file is not the
        first item in the zip file, this method will rewrite it.
    """
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


class NDataHandler(object):
    """
        A handler object for ndata files.

        ndata files are a zip file consisting of data.npy file and a metadata.json file.
        Both files must be uncompressed.

        The handler will read zip files where the metadata.json file is the first of the
        two files; however it will always make sure data is the first file upon writing.

        The handler is meant to be fully independent so that it can easily be plugged into
        earlier versions of Swift as it evolves.

        :param data_dir: The basic directory from which reference are based

        TODO: Move NDataHandler into a plug-in
    """

    def __init__(self, data_dir):
        self.__data_dir = data_dir

    def get_reference(self, file_path):
        """
            Return a reference for the file path.

            :param file_path: the absolute file path for ndata file
            :return: the reference string for the file

            The absolute file path should refer to a file within the data directory
            of this object.
        """
        relative_file = os.path.relpath(file_path, self.__data_dir)
        return os.path.splitext(relative_file)[0]

    def is_matching(self, file_path):
        """
            Return whether the given absolute file path is an ndata file.
        """
        if file_path.endswith(".ndata") and os.path.exists(file_path):
            try:
                with open(file_path, "r+b") as fp:
                    local_files, dir_files, eocd = parse_zip(fp)
                    contains_data = "data.npy" in dir_files
                    contains_metadata = "metadata.json" in dir_files
                    file_count = contains_data + contains_metadata  # use fact that True is 1, False is 0
                    # TODO: make sure ndata isn't compressed, or handle it
                    return len(dir_files) == file_count and file_count > 0
            except Exception, e:
                logging.error("Exception parsing ndata file: %s", file_path)
                logging.error(str(e))
        return False

    def write_data(self, reference, data, file_datetime):
        """
            Write data to the ndata file specified by reference.

            :param reference: the reference to which to write
            :param data: the numpy array data to write
            :param file_datetime: the datetime for the file
        """
        assert data is not None
        data_file_path = reference + ".ndata"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        #logging.debug("WRITE data file %s for %s", absolute_file_path, key)
        make_directory_if_needed(os.path.dirname(absolute_file_path))
        _, properties = self.read_properties(reference) if os.path.exists(absolute_file_path) else dict()
        write_zip(absolute_file_path, data, properties)
        # convert to utc time. this is temporary until datetime is cleaned up (again) and we can get utc directly from datetime.
        timestamp = calendar.timegm(file_datetime.timetuple()) + (datetime.datetime.utcnow() - datetime.datetime.now()).total_seconds()
        os.utime(absolute_file_path, (time.time(), timestamp))

    def write_properties(self, reference, properties, file_datetime):
        """
            Write properties to the ndata file specified by reference.

            :param reference: the reference to which to write
            :param properties: the dict to write to the file
            :param file_datetime: the datetime for the file
        """
        data_file_path = reference + ".ndata"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        #logging.debug("WRITE properties %s for %s", absolute_file_path, key)
        make_directory_if_needed(os.path.dirname(absolute_file_path))
        exists = os.path.exists(absolute_file_path)
        if exists:
            rewrite_zip(absolute_file_path, properties)
        else:
            write_zip(absolute_file_path, None, properties)
        # convert to utc time. this is temporary until datetime is cleaned up (again) and we can get utc directly from datetime.
        timestamp = calendar.timegm(file_datetime.timetuple()) + (datetime.datetime.utcnow() - datetime.datetime.now()).total_seconds()
        os.utime(absolute_file_path, (time.time(), timestamp))

    def read_properties(self, reference):
        """
            Read properties from the ndata file reference

            :param reference: the reference from which to read
            :return: a tuple of the item_uuid and a dict of the properties
        """
        data_file_path = reference + ".ndata"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        with open(absolute_file_path, "rb") as fp:
            local_files, dir_files, eocd = parse_zip(fp)
            properties = read_json(fp, local_files, dir_files, "metadata.json")
        item_uuid = uuid.UUID(properties["uuid"])
        return item_uuid, properties

    def read_data(self, reference):
        """
            Read data from the ndata file reference

            :param reference: the reference from which to read
            :return: a numpy array of the data; maybe None
        """
        data_file_path = reference + ".ndata"
        absolute_file_path = os.path.join(self.__data_dir, data_file_path)
        #logging.debug("READ data file %s", absolute_file_path)
        with open(absolute_file_path, "rb") as fp:
            local_files, dir_files, eocd = parse_zip(fp)
            return read_data(fp, local_files, dir_files, "data.npy")
        return None

    def remove(self, reference):
        """
            Remove the ndata file reference

            :param reference: the reference to remove
        """
        for suffix in ["ndata"]:
            data_file_path = reference + "." + suffix
            absolute_file_path = os.path.join(self.__data_dir, data_file_path)
            #logging.debug("DELETE data file %s", absolute_file_path)
            if os.path.isfile(absolute_file_path):
                os.remove(absolute_file_path)
