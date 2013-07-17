# standard libraries
import importlib
import inspect
import logging
import os
import sys
import unittest


_testSuites = []

def loadPlugIns():
    # calculate the relative path of the plug-in folder. this will be different depending on platform.
    localpath = os.path.dirname(os.path.realpath(__file__))
    if sys.platform == "win32":
        plugins_dir = os.path.abspath(os.path.join(os.path.join(os.path.join(localpath, ".."), ".."), "PlugIns"))
    else:
        plugins_dir = os.path.abspath(os.path.join(os.path.join(os.path.join(os.path.join(localpath, ".."), ".."), ".."), "PlugIns"))
    sys.path.append(plugins_dir)
    logging.debug(plugins_dir)
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
        except ImportError, ex:
            logging.info("Plug-in '" + plugin_dir + "' NOT loaded. " + str(ex))

def appendTestSuites(suites):
    _testSuites.extend(suites)

def testSuites():
    return _testSuites
