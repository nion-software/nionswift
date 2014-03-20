# standard libraries
import importlib
import inspect
import logging
import os
import sys
import traceback
import unittest

__test_suites = []


def load_plug_ins(ui, root_dir):
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
                    # First load the module.
                    module = importlib.import_module(plugin_dir)
                    # Now scan through the module and look for tests.
                    tests = []
                    for member in inspect.getmembers(module):
                        if inspect.ismodule(member[1]) and member[0].endswith("_test"):
                            for maybe_a_class in inspect.getmembers(member[1]):
                                if inspect.isclass(maybe_a_class[1]) and maybe_a_class[0].startswith("Test"):
                                    # It is a class... add it to the test suite.
                                    tests.append(maybe_a_class[0])
                                    cls = getattr(member[1], maybe_a_class[0])
                                    __test_suites.append(unittest.TestLoader().loadTestsFromTestCase(cls))
                    plugin_loaded_str = "Plug-in '" + plugin_dir + "' loaded."
                    list_of_tests_str = " Tests: " + ",".join(tests) if len(tests) > 0 else ""
                    logging.info(plugin_loaded_str + list_of_tests_str)
                except Exception:
                    logging.info("Plug-in '" + plugin_dir + "' NOT loaded.")
                    logging.info(traceback.format_exc())
                    logging.info("--------")


def append_test_suites(suites):
    __test_suites.extend(suites)


def test_suites():
    return __test_suites
