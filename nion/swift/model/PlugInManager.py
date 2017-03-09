# standard libraries
import collections
import copy
import importlib
import importlib.util
import inspect
import json
import logging
import os
import re
import sys
import traceback
import unittest

from nion.swift.model import Utility


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

def load_plug_in(plugin_dir: str):
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
        list_of_tests_str = " Tests: " + ",".join(tests) if len(tests) > 0 else ""
        logging.info(plugin_loaded_str + list_of_tests_str)
        return module
    except RequirementsException as e:
        logging.info("Plug-in '" + plugin_dir + "' NOT loaded. %s", e.reason)
    except Exception as e:
        logging.info("Plug-in '" + plugin_dir + "' NOT loaded.")
        logging.info(traceback.format_exc())
        logging.info("--------")
    return None

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

    PlugInDir = collections.namedtuple("PlugInDir", ["directory", "relative_path"])
    plugin_dirs = list()

    plugin_paths = list()

    for subdirectory in subdirectories:

        packages_dir = os.path.abspath(os.path.join(subdirectory, "Packages"))
        plugins_dir = os.path.abspath(os.path.join(subdirectory, "PlugIns"))

        if os.path.exists(packages_dir):
            logging.info("Using packages from %s", packages_dir)
            sys.path.append(packages_dir)

        if os.path.exists(plugins_dir) and not plugins_dir in plugin_paths:
            logging.info("Loading plug-ins from %s", plugins_dir)
            sys.path.append(plugins_dir)

            sorted_relative_paths = sorted([d for d in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, d))])
            plugin_dirs.extend([PlugInDir(plugins_dir, sorted_relative_path) for sorted_relative_path in sorted_relative_paths])

            plugin_paths.append(plugins_dir)
        else:
            logging.info("NOT Loading plug-ins from %s (missing)", plugins_dir)

    invalid_manifests = list()
    version_map = dict()
    module_exists_map = dict()

    progress = True
    while progress:
        progress = False
        plugin_dirs_copy = copy.deepcopy(plugin_dirs)
        plugin_dirs = list()
        for directory, relative_path in plugin_dirs_copy:
            plugin_dir = os.path.join(directory, relative_path)
            manifest_path = os.path.join(plugin_dir, "manifest.json")
            if manifest_path in invalid_manifests:
                continue
            manifest = None
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path) as f:
                        manifest = json.load(f)
                except Exception as e:
                    logging.info("Cannot read manifest file from %s", manifest_path)
                    logging.info(e)
            if manifest:
                # print("CHECKING ", manifest)
                manifest_valid = True
                if not "name" in manifest:
                    logging.info("Invalid manifest (missing 'name'): %s", manifest_path)
                    manifest_valid = False
                if not "identifier" in manifest:
                    logging.info("Invalid manifest (missing 'identifier'): %s", manifest_path)
                    manifest_valid = False
                if "identifier" in manifest and not re.match("[_\-a-zA-Z][_\-a-zA-Z0-9.]*$", manifest["identifier"]):
                    logging.info("Invalid manifest (invalid 'identifier': '%s'): %s", manifest["identifier"], manifest_path)
                    manifest_valid = False
                if not "version" in manifest:
                    logging.info("Invalid manifest (missing 'version'): %s", manifest_path)
                    manifest_valid = False
                if "requires" in manifest and not isinstance(manifest["requires"], list):
                    logging.info("Invalid manifest ('requires' not a list): %s", manifest_path)
                    manifest_valid = False
                if not manifest_valid:
                    continue
                for module in manifest.get("modules", list()):
                    if module in module_exists_map:
                        module_exists = module_exists_map.get(module)
                    else:
                        module_exists = importlib.util.find_spec(module) is not None
                        module_exists_map[module] = module_exists
                    if not module_exists:
                        logging.info("Plug-in '" + relative_path + "' NOT loaded.")
                        logging.info("Cannot satisfy requirement (%s): %s", module, manifest_path)
                        manifest_valid = False
                        break
                for requirement in manifest.get("requires", list()):
                    # TODO: see https://packaging.pypa.io/en/latest/
                    requirement_components = requirement.split()
                    if len(requirement_components) != 3 or requirement_components[1] != "~=":
                        logging.info("Invalid manifest (requirement '%s' invalid): %s", requirement, manifest_path)
                        manifest_valid = False
                        break
                    identifier, operator, version_specifier = requirement_components[0], requirement_components[1], requirement_components[2]
                    if identifier in version_map:
                        if Utility.compare_versions("~" + version_specifier, version_map[identifier]) != 0:
                            logging.info("Plug-in '" + relative_path + "' NOT loaded.")
                            logging.info("Cannot satisfy requirement (%s): %s", requirement, manifest_path)
                            manifest_valid = False
                            break
                    else:
                        # requirements not loaded yet; add back to plugin_dirs, but don't mark progress since nothing was loaded.
                        logging.info("Plug-in '" + relative_path + "' delayed (%s).", requirement)
                        plugin_dirs.append(PlugInDir(directory, relative_path))
                        manifest_valid = False
                        break
                if not manifest_valid:
                    continue
                version_map[manifest["identifier"]] = manifest["version"]
            # read the manifests, if any
            # repeat loop of plug-ins until no plug-ins left in the list
            #   if all dependencies satisfied for a plug-in, load it
            #   otherwise defer until next round
            #   stop if no plug-ins loaded in the round
            #   count on the user to have correct dependencies
            module = load_plug_in(relative_path)
            if module:
                __modules.append(module)
            progress = True
    for directory, relative_path in plugin_dirs:
        logging.info("Plug-in '" + relative_path + "' NOT loaded (requirements).")

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
