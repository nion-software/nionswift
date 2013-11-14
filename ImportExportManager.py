# standard libraries
import logging
import os

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import Decorators
from nion.swift import Image


class ImportExportIncompatibleDataError(Exception):
    pass


class ImportExportHandler(object):

    # Extensions should not include a period.
    def __init__(self, name, extensions):
        self.name = name
        self.extensions = extensions

    def can_read(self):
        return True

    # return a data item
    def read(self, ui, file_path, extension):
        with open(file_path, 'rb') as f:
            return self.read_file(file_path, extension, f)

    # return a data item
    def read_file(self, file_path, extension, file):
        data = self.read_data(extension, file)
        #logging.debug("read %s %s %s", file, extension, data)
        if data is not None:
            root, filename = os.path.split(file_path)
            title, _ = os.path.splitext(filename)
            data_item = DataItem.DataItem()
            with data_item.create_data_accessor() as data_accessor:
                data_accessor.master_data = data
            data_item.title = title
            return data_item
        return None

    # return data
    def read_data(self, extension, file):
        return None

    def can_write(self, data_item, extension):
        return False

    def write(self, ui, data_item, path, extension):
        with open(path, 'wb') as f:
            self.write_file(data_item, extension, f)

    def write_file(self, data_item, extension, file):
        with data_item.create_data_accessor() as data_accessor:
            data = data_accessor.data
        if data is not None:
            self.write_data(data, extension, file)

    def write_data(self, data, extension, file):
        pass


@Decorators.singleton
class ImportExportManager(object):
    """
    Keeps track of import/export plugins.
    """
    def __init__(self):
        # we store a of dicts dicts containing extensions,
        # load_func, save_func, keyed by name.
        self.__io_handlers = []

    def register_io_handler(self, io_handler):
        self.__io_handlers.append(io_handler)

    def unregister_io_handler(self, io_handler):
        self.__io_handlers.remove(io_handler)

    def get_readers(self):
        readers = []
        for io_handler in self.__io_handlers:
            if io_handler.can_read():
                readers.append(io_handler)
        return readers

    def get_writers_for_data_item(self, data_item):
        writers = []
        for io_handler in self.__io_handlers:
            for extension in io_handler.extensions:
                if io_handler.can_write(data_item, extension):
                    writers.append(io_handler)
                    break  # from iterating extensions
        return writers

    # read file, return data item
    def read(self, ui, path):
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            for io_handler in self.__io_handlers:
                if extension in io_handler.extensions:
                    return io_handler.read(ui, path, extension)
        return None

    def write(self, ui, data_item, path):
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            for io_handler in self.__io_handlers:
                if extension in io_handler.extensions and io_handler.can_write(data_item, extension):
                    io_handler.write(ui, data_item, path, extension)


class StandardImportExportHandler(ImportExportHandler):

    def __init__(self, name, extensions):
        super(StandardImportExportHandler, self).__init__(name, extensions)

    def read(self, ui, path, extension):
        data = Image.read_image_from_file(ui, path)
        if data is not None:
            root, filename = os.path.split(path)
            title, _ = os.path.splitext(filename)
            data_item = DataItem.DataItem()
            with data_item.create_data_accessor() as data_accessor:
                data_accessor.master_data = data
            data_item.title = title
            return data_item
        return None

    def can_write(self, data_item, extension):
        return len(data_item.spatial_shape) == 2

    def write(self, ui, data_item, path, extension):
        data = data_item.preview_2d
        if data is not None:
            ui.save_rgba_data_to_file(data, path, extension)


ImportExportManager().register_io_handler(StandardImportExportHandler("JPEG", ["jpg", "jpeg"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("PNG", ["png"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("TIFF", ["tif", "tiff"]))
