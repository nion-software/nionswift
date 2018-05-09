# standard libraries
import importlib
import inspect
import os
import sys
import unittest

# third party libraries
# None

# local libraries
from nion.swift.model import PlugInManager


suites = []
suite_dict = {}
alltests = None


# scan through directory and look for tests (files ending in test.py)
# load the module and add the tests
def load_tests(packages):
    global suites
    global suite_dict
    global alltests

    base_prefix = sys.base_prefix
    directories = set()
    for path in sys.path:
        if not path.startswith(base_prefix):
            directories.add(path)
    for package in packages:
        for directory in directories:
            test_dir = os.path.join(directory, *package.split("."), "test")
            if os.path.isdir(test_dir):
                for file in os.listdir(test_dir):
                    if file.endswith("_test.py"):
                        module_name = package + ".test." + file.replace('.py', '')
                        module = importlib.import_module(module_name)
                        for maybe_a_class in inspect.getmembers(module):
                            if inspect.isclass(maybe_a_class[1]) and maybe_a_class[0].startswith("Test"):
                                test_name = maybe_a_class[0]
                                # It is a class... add it to the test suite.
                                cls = getattr(module, test_name)
                                suite = unittest.TestLoader().loadTestsFromTestCase(cls)
                                suites.append(suite)
                                suite_dict[test_name] = suite

    suites.extend(PlugInManager.test_suites())

    alltests = unittest.TestSuite(suites)

def run_all_tests():
    unittest.TextTestRunner(verbosity=2).run(alltests)

def run_test(test_name):
    unittest.TextTestRunner(verbosity=2).run(suite_dict[test_name])
