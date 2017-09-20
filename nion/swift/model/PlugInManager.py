# standard libraries
import collections
import copy
import importlib
import importlib.util
import inspect
import json
import logging
import os
import pkgutil
import re
import sys
import traceback
import unittest

from nion.swift.model import Utility
from nion.ui import Declarative


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

class APIBroker:
    def get_api(self, *args, **kwargs):
        global api_broker_fn
        return api_broker_fn(*args, **kwargs)
    def get_ui(self, version):
        actual_version = "1.0.0"
        if Utility.compare_versions(version, actual_version) > 0:
            raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
        return Declarative.DeclarativeUI()

extensions = []

def load_plug_in(module_path: str, module_name: str):
    try:
        # First load the module.
        module = importlib.import_module(module_name)
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
        plugin_loaded_str = "Plug-in '" + module_name + "' loaded (" + module_path + ")."
        list_of_tests_str = " Tests: " + ",".join(tests) if len(tests) > 0 else ""
        logging.info(plugin_loaded_str + list_of_tests_str)
        return module
    except RequirementsException as e:
        logging.info("Plug-in '" + module_name + "' NOT loaded. %s (" + module_path + ")", e.reason)
    except Exception as e:
        logging.info("Plug-in '" + module_name + "' NOT loaded (" + module_path + ").")
        logging.info(traceback.format_exc())
        logging.info("--------")
    return None


class ModuleAdapter:
    def __init__(self, package_name, module_info):
        self.module_name = package_name + "." + module_info.name
        self.module_path = package_name
        self.manifest_path = "N/A"
        self.manifest = dict()
        path = getattr(module_info.module_finder, 'path', None)
        if path:
            self.manifest_path = os.path.join(path, module_info.name, "manifest.json")
            if os.path.exists(self.manifest_path):
                try:
                    with open(self.manifest_path) as f:
                        self.manifest.update(json.load(f))
                except Exception as e:
                    logging.info("Cannot read manifest file from %s", self.manifest_path)
                    logging.info(e)
        get_data = getattr(module_info.module_finder, 'get_data', None)
        if get_data:
            try:
                json_data = get_data(os.path.join(package_name, module_info.name, "manifest.json"))
                self.manifest.update(json.loads(json_data))
            except Exception as e:
                logging.info("Cannot read manifest file from %s", module_info.module_finder.archive)
                logging.info(e)
        self.manifest.setdefault("name", self.module_name)
        self.manifest.setdefault("identifier", self.module_name)
        self.manifest.setdefault("version", "0.0.0")

    def load(self):
        return load_plug_in(self.module_path, self.module_name)


class PlugInAdapter:
    def __init__(self, directory, relative_path):
        plugin_dir = os.path.join(directory, relative_path)
        self.manifest_path = os.path.join(plugin_dir, "manifest.json")
        self.module_name = relative_path
        self.module_path = directory
        self.manifest = None
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path) as f:
                    self.manifest = json.load(f)
            except Exception as e:
                logging.info("Cannot read manifest file from %s", self.manifest_path)
                logging.info(e)

    def load(self):
        return load_plug_in(self.module_path, self.module_name)


def load_plug_ins(app, root_dir):
    """Load plug-ins."""
    global extensions

    ui = app.ui

    # a list of directories in which sub-directories PlugIns will be searched.
    subdirectories = []

    # the default location is where the directory main packages are located.
    if root_dir:
        subdirectories.append(root_dir)

    # also search the default data location; create directory there if it doesn't exist to make it easier for user.
    # default data location will be application specific.
    data_location = ui.get_data_location()
    if data_location is not None:
        subdirectories.append(data_location)
        # create directories here if they don't exist
        plugins_dir = os.path.abspath(os.path.join(data_location, "PlugIns"))
        if not os.path.exists(plugins_dir):
            logging.info("Creating plug-ins directory %s", plugins_dir)
            os.makedirs(plugins_dir)

    # search the Nion/Swift subdirectory of the default document location too,
    # but don't create directories here - avoid polluting user visible directories.
    document_location = ui.get_document_location()
    if document_location is not None:
        subdirectories.append(os.path.join(document_location, "Nion", "Swift"))
        # do not create them in documents if they don't exist. this location is optional.

    # build a list of directories that will be loaded as plug-ins.
    PlugInDir = collections.namedtuple("PlugInDir", ["directory", "relative_path"])
    plugin_dirs = list()

    # track directories that have already been searched.
    seen_plugin_dirs = list()

    # for each subdirectory, look in PlugIns for sub-directories that represent the plug-ins.
    for subdirectory in subdirectories:
        plugins_dir = os.path.abspath(os.path.join(subdirectory, "PlugIns"))

        if os.path.exists(plugins_dir) and not plugins_dir in seen_plugin_dirs:
            logging.info("Loading plug-ins from %s", plugins_dir)

            # add the PlugIns directory to the system import path.
            sys.path.append(plugins_dir)

            # now build a list of sub-directories representing plug-ins within plugins_dir.
            sorted_relative_paths = sorted([d for d in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, d))])
            plugin_dirs.extend([PlugInDir(plugins_dir, sorted_relative_path) for sorted_relative_path in sorted_relative_paths])

            # mark plugins_dir as 'seen' to avoid search it twice.
            seen_plugin_dirs.append(plugins_dir)
        else:
            logging.info("NOT Loading plug-ins from %s (missing)", plugins_dir)

    version_map = dict()
    module_exists_map = dict()

    plugin_adapters = list()

    import nionswift_plugin
    for module_info in pkgutil.iter_modules(nionswift_plugin.__path__):
        plugin_adapters.append(ModuleAdapter(nionswift_plugin.__name__, module_info))

    for directory, relative_path in plugin_dirs:
        plugin_adapters.append(PlugInAdapter(directory, relative_path))

    progress = True
    while progress:
        progress = False
        plugin_adapters_copy = copy.deepcopy(plugin_adapters)
        plugin_adapters = list()
        for plugin_adapter in plugin_adapters_copy:
            manifest_path = plugin_adapter.manifest_path
            manifest = plugin_adapter.manifest
            if manifest:
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
                        logging.info("Plug-in '" + plugin_adapter.module_name + "' NOT loaded (" + plugin_adapter.module_path + ").")
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
                            logging.info("Plug-in '" + plugin_adapter.module_name + "' NOT loaded (" + plugin_adapter.module_path + ").")
                            logging.info("Cannot satisfy requirement (%s): %s", requirement, manifest_path)
                            manifest_valid = False
                            break
                    else:
                        # requirements not loaded yet; add back to plugin_adapters, but don't mark progress since nothing was loaded.
                        logging.info("Plug-in '" + plugin_adapter.module_name + "' delayed (%s) (" + plugin_adapter.module_path + ").", requirement)
                        plugin_adapters.append(plugin_adapter)
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
            module = plugin_adapter.load()
            if module:
                __modules.append(module)
            progress = True
    for plugin_adapter in plugin_adapters:
        logging.info("Plug-in '" + plugin_adapter.module_name + "' NOT loaded (requirements) (" + plugin_adapter.module_path + ").")

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
