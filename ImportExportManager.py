# standard libraries
import os

# third party libraries
# None

# local libraries
# None


class ImportExportIncompatibleDataError(Exception):
    pass


class ImportExportManager(object):
    """
    Keeps track of import/export plugins.
    """
    def __init__(self):
        # we store a of dicts dicts containing extensions,
        # load_func, save_func, keyed by name.
        self.io_extensions = {}

    def get_io_for_extension(self, extension):
        """
        Return the registerd io name that can handle the extension.
        Extension should not include a period.
        """
        for k, v in self.io_extensions.iteritems():
            if extension in v["extensions"]:
                return k

    def get_io_for_file(self, filepath):
        root, ext = os.path.splitext(filepath)
        if ext:
            # we remove the leading "."
            return self.get_io_for_extension(ext[1:])

    def register_io(self, name, extensions, load_func, save_func):
        """
        Registers the load_func, save_func functions for handling any files
        ending with an extension in extensions. Extensions should not include
        a period.

        load_func should take a file-like object and return a numpy array.

        save_func takes a numpy array and writable file-like object and should
        write the array to the file.
        """
        self.io_extensions[name] = {"extensions": extensions,
                                    "load_func": load_func,
                                    "save_func": save_func}

    def unregister_io(self, name):
        if name in self.io_extensions:
            del self.io_extensions[name]

    def get_all_extensions(self, savable, loadable):
        """
        Returns a list of (name, extensions) tuples from all registered handlers.

        If savable is True, only plugins supporting saving are returned.
        If loadable is True, only plugins supported loading are returned.
        """
        ret = []
        for k, v in self.io_extensions.iteritems():
            if savable and not v["save_func"]:
                continue
            if loadable and not v["load_func"]:
                continue
            ret.append((k, v["extensions"]))
        return ret

    def load_file(self, filepath):
        k = self.get_io_for_file(filepath)
        if k:
            with open(filepath, 'rb') as f:
                return self.io_extensions[k]["load_func"](f)

    def save_file(self, data, filepath):
        k = self.get_io_for_file(filepath)
        if k:
            with open(filepath, 'wb') as f:
                return self.io_extensions[k]["save_func"](data, f)
        return False  # no handler found

