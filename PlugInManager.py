# standard libraries
import importlib
import inspect
import logging
import os
import sys
import traceback
import unittest

_testSuites = []


def loadPlugIns():
    # calculate the relative path of the plug-in folder. this will be different depending on platform.
    # we'll let command line arguments overwrite the plugin folder location
    plugins_dir = None

    for flag, arg in zip(sys.argv, sys.argv[1:]):
        if flag.lower() == "-pluginpath":
            plugins_dir = os.path.abspath(arg)

    if not plugins_dir:
        # in Windows, we generally have
        # |   NionImaging.exe
        # +---nion
        # |   |   init.py
        # |   \---swift
        # |       |   ...
        # |       |   PluginManager.py
        # |       |   ...
        # +---PlugIns
        # |   \---PluginOne
        # |       |   init.py
        # |       ...
        #
        # and under Mac
        # +---MacOs
        # |       NionImaging.app
        # +---Resources
        # |   \---nion
        # |       |   init.py
        # |       \---swift
        # |           |   ...
        # |           |   PluginManager.py
        # |           |   ...
        # +---PlugIns
        # |   \---PluginOne
        # |       |   init.py
        # |       ...

        root_dir = os.path.dirname(os.path.realpath(__file__))
        path_ascend_count = 2 if sys.platform == "win32" or sys.platform.startswith("linux") else 3
        for i in range(path_ascend_count):
            root_dir = os.path.dirname(root_dir)
        packages_dir = os.path.abspath(os.path.join(root_dir, "Packages"))
        plugins_dir = os.path.abspath(os.path.join(root_dir, "PlugIns"))

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
                                _testSuites.append(unittest.TestLoader().loadTestsFromTestCase(cls))
                logging.info("Plug-in '" + plugin_dir + "' loaded." + (" Tests: " + ",".join(tests) if len(tests) > 0 else ""))
            except Exception as e:
                logging.info("Plug-in '" + plugin_dir + "' NOT loaded.")
                logging.info(traceback.format_exc())
                logging.info("--------")

def appendTestSuites(suites):
    _testSuites.extend(suites)

def testSuites():
    return _testSuites
