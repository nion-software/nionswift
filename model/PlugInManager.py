# standard libraries
import importlib
import inspect
import logging
import os
import sys
import traceback
import unittest


__modules = []
__test_suites = []


class RequirementsException(Exception):
    """An exception for when a plug-in can't load because it can't meet the necessary requirements."""
    def __init__(self, reason):
        self.reason = reason


api_broker_fn = None

def register_api_broker_fn(new_api_broker_fn):
    global api_broker_fn
    api_broker_fn = new_api_broker_fn

extensions = []

def load_plug_ins(app, root_dir):
    global extensions

    ui = app.ui

    # calculate the relative path of the plug-in folder. this will be different depending on platform.
    # we'll let command line arguments overwrite the plugin folder location
    subdirectories = []

    subdirectories.append(root_dir)

    data_location = ui.get_data_location()
    if data_location is not None:
        subdirectories.append(data_location)
        # create directories here if they don't exist
        packages_dir = os.path.abspath(os.path.join(data_location, "Packages"))
        plugins_dir = os.path.abspath(os.path.join(data_location, "PlugIns"))
        if not os.path.exists(packages_dir):
            logging.info("Creating packages directory %s", packages_dir)
            os.makedirs(packages_dir)
        if not os.path.exists(plugins_dir):
            logging.info("Creating plug-ins directory %s", plugins_dir)
            os.makedirs(plugins_dir)

    document_location = ui.get_document_location()
    if document_location is not None:
        subdirectories.append(os.path.join(document_location, "Nion", "Swift"))
        # do not create them in documents if they don't exist. this location is optional.

    for subdirectory in subdirectories:

        packages_dir = os.path.abspath(os.path.join(subdirectory, "Packages"))
        plugins_dir = os.path.abspath(os.path.join(subdirectory, "PlugIns"))

        if os.path.exists(packages_dir):
            logging.info("Using packages from %s", packages_dir)
            sys.path.append(packages_dir)

        if os.path.exists(plugins_dir):
            logging.info("Loading plug-ins from %s", plugins_dir)
            sys.path.append(plugins_dir)

            plugin_dirs = [d for d in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, d))]
            for plugin_dir in sorted(plugin_dirs):
                try:
                    class APIBroker(object):
                        def get_api(self, *args, **kwargs):
                            global api_broker_fn
                            return api_broker_fn(*args, **kwargs)

                    # First load the module.
                    module = importlib.import_module(plugin_dir)
                    # Now scan through the module and look for extensions and tests.
                    tests = []
                    for member in inspect.getmembers(module):
                        if inspect.ismodule(member[1]):
                            if member[0].endswith("_test"):
                                for maybe_a_class in inspect.getmembers(member[1]):
                                    if inspect.isclass(maybe_a_class[1]):
                                        if maybe_a_class[0].startswith("Test"):
                                            # It is a class... add it to the test suite.
                                            tests.append(maybe_a_class[0])
                                            cls = getattr(member[1], maybe_a_class[0])
                                            __test_suites.append(unittest.TestLoader().loadTestsFromTestCase(cls))
                            for maybe_a_class in inspect.getmembers(member[1]):
                                if inspect.isclass(maybe_a_class[1]):
                                    if maybe_a_class[0].endswith("Extension"):
                                        cls = getattr(member[1], maybe_a_class[0])
                                        extension_id = getattr(cls, "extension_id", None)
                                        if extension_id:
                                            extensions.append(cls(APIBroker()))
                        if inspect.isclass(member[1]) and member[0].endswith("Extension"):
                            cls = getattr(module, member[0])
                            extension_id = getattr(cls, "extension_id", None)
                            if extension_id:
                                extensions.append(cls(APIBroker()))
                    plugin_loaded_str = "Plug-in '" + plugin_dir + "' loaded."
                    __modules.append(module)
                    list_of_tests_str = " Tests: " + ",".join(tests) if len(tests) > 0 else ""
                    logging.info(plugin_loaded_str + list_of_tests_str)
                except RequirementsException as e:
                    logging.info("Plug-in '" + plugin_dir + "' NOT loaded. %s", e.reason)
                except Exception as e:
                    logging.info("Plug-in '" + plugin_dir + "' NOT loaded.")
                    logging.info(traceback.format_exc())
                    logging.info("--------")

    notify_modules("run")

def unload_plug_ins():
    global extensions
    for extension in reversed(extensions):
        try:
            extension.close()
        except Exception as e:
            logging.info(traceback.format_exc())

    extensions = []

def notify_modules(method_name, *args, **kwargs):
    for module in __modules:
        for member in inspect.getmembers(module):
            if inspect.isfunction(member[1]) and member[0] == method_name:
                try:
                    member[1](*args, **kwargs)
                except Exception as e:
                    logging.info("Plug-in '" + str(module) + "' exception during '" + method_name + "'.")
                    logging.info(traceback.format_exc())
                    logging.info("--------")


def append_test_suites(suites):
    __test_suites.extend(suites)


def test_suites():
    return __test_suites
