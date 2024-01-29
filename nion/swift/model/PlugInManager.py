from __future__ import annotations

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
import time
import traceback
import types
import typing
import unittest

from nion.swift.model import Utility
from nion.ui import Declarative

PersistentDictType = typing.Dict[str, typing.Any]
_ModuleInfoType = typing.Any

__modules: typing.List[types.ModuleType] = list()
__test_suites: typing.List[unittest.suite.TestSuite] = list()

logger = logging.getLogger("loader_progress")


class RequirementsException(Exception):
    """An exception for when a plug-in can't load because it can't meet the necessary requirements."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


ApiBrokerFn = typing.Callable[..., typing.Any]
api_broker_fn = typing.cast(ApiBrokerFn, None)


def register_api_broker_fn(new_api_broker_fn: ApiBrokerFn) -> None:
    global api_broker_fn
    api_broker_fn = new_api_broker_fn


class APIBroker:
    def get_api(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        global api_broker_fn
        return api_broker_fn(*args, **kwargs)

    def get_ui(self, version: str) -> Declarative.DeclarativeUI:
        actual_version = "1.0.0"
        if Utility.compare_versions(version, actual_version) > 0:
            raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
        return Declarative.DeclarativeUI()


extensions: typing.List[typing.Any] = list()


def load_plug_in(module_path: str, module_name: str) -> typing.Optional[types.ModuleType]:
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
                                test_suite = unittest.TestLoader().loadTestsFromTestCase(cls)
                                __test_suites.append(test_suite)
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
        logger.info(plugin_loaded_str + list_of_tests_str)
        return module
    except RequirementsException as e:
        logger.info("Plug-in '" + module_name + "' NOT loaded. %s (" + module_path + ")", e.reason)
    except Exception as e:
        logger.info("Plug-in '" + module_name + "' NOT loaded (" + module_path + ").")
        logger.info(traceback.format_exc())
        logger.info("--------")
    return None


class _AdapterProtocol(typing.Protocol):
    module_name: str
    module_path: str
    loaded_module: typing.Optional[types.ModuleType]
    manifest_path: str
    manifest: PersistentDictType

    def load(self) -> None: ...


class ModuleAdapter(_AdapterProtocol):
    def __init__(self, package_name: str, module_info: _ModuleInfoType) -> None:
        self.module_name = package_name + "." + module_info.name
        self.module_path = package_name
        self.loaded_module: typing.Optional[types.ModuleType] = None
        self.manifest_path = "N/A"
        self.manifest: PersistentDictType = dict()
        path = getattr(module_info.module_finder, 'path', None)
        if path:
            self.manifest_path = os.path.join(path, module_info.name, "manifest.json")
            if os.path.exists(self.manifest_path):
                try:
                    with open(self.manifest_path) as f:
                        self.manifest.update(json.load(f))
                except Exception as e:
                    logger.info("Cannot read manifest file from %s", self.manifest_path)
                    logger.info(e)
        get_data = getattr(module_info.module_finder, 'get_data', None)
        if get_data:
            try:
                json_data = get_data(os.path.join(package_name, module_info.name, "manifest.json"))
                self.manifest.update(json.loads(json_data))
            except Exception as e:
                logger.info("Cannot read manifest file from %s", module_info.module_finder.archive)
                logger.info(e)
        self.manifest.setdefault("name", self.module_name)
        self.manifest.setdefault("identifier", self.module_name)
        self.manifest.setdefault("version", "0.0.0")

    def load(self) -> None:
        self.loaded_module = load_plug_in(self.module_path, self.module_name)


class PlugInAdapter(_AdapterProtocol):
    def __init__(self, directory: str, relative_path: str) -> None:
        plugin_dir = os.path.join(directory, relative_path)
        self.manifest_path = os.path.join(plugin_dir, "manifest.json")
        self.module_name = relative_path
        self.module_path = directory
        self.loaded_module: typing.Optional[types.ModuleType] = None
        self.manifest: PersistentDictType = dict()
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path) as f:
                    self.manifest = json.load(f)
            except Exception as e:
                logger.info("Cannot read manifest file from %s", self.manifest_path)
                logger.info(e)

    def load(self) -> None:
        self.loaded_module = load_plug_in(self.module_path, self.module_name)


class ApplicationLike(typing.Protocol):
    pass


def load_plug_ins(document_location: str, data_location: str, root_dir: typing.Optional[str]) -> None:
    """Load plug-ins."""
    global extensions

    # a list of directories in which sub-directories PlugIns will be searched.
    subdirectories = []

    # the default location is where the directory main packages are located.
    if root_dir:
        subdirectories.append(root_dir)

    # also search the default data location; create directory there if it doesn't exist to make it easier for user.
    # default data location will be application specific.
    if data_location is not None:
        subdirectories.append(data_location)
        # create directories here if they don't exist
        plugins_dir = os.path.abspath(os.path.join(data_location, "PlugIns"))
        if not os.path.exists(plugins_dir):
            logger.info("Creating plug-ins directory %s", plugins_dir)
            os.makedirs(plugins_dir)

    # search the Nion/Swift subdirectory of the default document location too,
    # but don't create directories here - avoid polluting user visible directories.
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
            logger.info("Loading plug-ins from %s", plugins_dir)

            # add the PlugIns directory to the system import path.
            sys.path.append(plugins_dir)

            # now build a list of sub-directories representing plug-ins within plugins_dir.
            sorted_relative_paths = sorted([d for d in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, d))])
            plugin_dirs.extend([PlugInDir(plugins_dir, sorted_relative_path) for sorted_relative_path in sorted_relative_paths])

            # mark plugins_dir as 'seen' to avoid search it twice.
            seen_plugin_dirs.append(plugins_dir)
        else:
            logger.info("NOT Loading plug-ins from %s (missing)", plugins_dir)

    version_map: PersistentDictType = dict()
    module_exists_map: typing.Dict[str, bool] = dict()

    plugin_adapters = list[_AdapterProtocol]()

    import nionswift_plugin
    for module_info in pkgutil.iter_modules(getattr(nionswift_plugin, "__path__")):
        plugin_adapters.append(ModuleAdapter(getattr(nionswift_plugin, "__name__"), module_info))

    for directory, relative_path in plugin_dirs:
        plugin_adapters.append(PlugInAdapter(directory, relative_path))

    ordered_module_adapters = list[_AdapterProtocol]()

    progress = True
    while progress:
        progress = False
        plugin_adapters_copy = copy.deepcopy(plugin_adapters)
        plugin_adapters = list[_AdapterProtocol]()
        for plugin_adapter in plugin_adapters_copy:
            manifest_path = plugin_adapter.manifest_path
            manifest = plugin_adapter.manifest
            if manifest:
                manifest_valid = True
                if not "name" in manifest:
                    logger.info("Invalid manifest (missing 'name'): %s", manifest_path)
                    manifest_valid = False
                if not "identifier" in manifest:
                    logger.info("Invalid manifest (missing 'identifier'): %s", manifest_path)
                    manifest_valid = False
                if "identifier" in manifest and not re.match(r"[_\-a-zA-Z][_\-a-zA-Z0-9.]*$", manifest["identifier"]):
                    logger.info("Invalid manifest (invalid 'identifier': '%s'): %s", manifest["identifier"], manifest_path)
                    manifest_valid = False
                if not "version" in manifest:
                    logger.info("Invalid manifest (missing 'version'): %s", manifest_path)
                    manifest_valid = False
                if "requires" in manifest and not isinstance(manifest["requires"], list):
                    logger.info("Invalid manifest ('requires' not a list): %s", manifest_path)
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
                        logger.info("Plug-in '" + plugin_adapter.module_name + "' NOT loaded (" + plugin_adapter.module_path + ").")
                        logger.info("Cannot satisfy requirement (%s): %s", module, manifest_path)
                        manifest_valid = False
                        break
                for requirement in manifest.get("requires", list()):
                    # TODO: see https://packaging.pypa.io/en/latest/
                    requirement_components = requirement.split()
                    if len(requirement_components) != 3 or requirement_components[1] != "~=":
                        logger.info("Invalid manifest (requirement '%s' invalid): %s", requirement, manifest_path)
                        manifest_valid = False
                        break
                    identifier, operator, version_specifier = requirement_components[0], requirement_components[1], requirement_components[2]
                    if identifier in version_map:
                        if Utility.compare_versions("~" + version_specifier, version_map[identifier]) != 0:
                            logger.info("Plug-in '" + plugin_adapter.module_name + "' NOT loaded (" + plugin_adapter.module_path + ").")
                            logger.info("Cannot satisfy requirement (%s): %s", requirement, manifest_path)
                            manifest_valid = False
                            break
                    else:
                        # requirements not loaded yet; add back to plugin_adapters, but don't mark progress since nothing was loaded.
                        logger.info("Plug-in '" + plugin_adapter.module_name + "' delayed (%s) (" + plugin_adapter.module_path + ").", requirement)
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
            plugin_adapter.load()
            if plugin_adapter.loaded_module:
                ordered_module_adapters.append(plugin_adapter)
                __modules.append(plugin_adapter.loaded_module)
            progress = True
    for plugin_adapter in plugin_adapters:
        logger.info("Plug-in '" + plugin_adapter.module_name + "' NOT loaded (requirements) (" + plugin_adapter.module_path + ").")

    for plugin_adapter in ordered_module_adapters:
        module = plugin_adapter.loaded_module
        assert module
        for member in inspect.getmembers(module):
            if inspect.isfunction(member[1]) and member[0] == "run":
                try:
                    start_time = time.time()
                    member[1]()
                    elapsed_s = int(time.time() - start_time)
                    logger.info(f"Plug-in '{plugin_adapter.module_name}' initialized ({elapsed_s}s)")
                except Exception as e:
                    logger.info("Plug-in '" + str(module) + "' exception during 'run'.")
                    logger.info(traceback.format_exc())
                    logger.info("--------")

def unload_plug_ins() -> None:
    global extensions
    for extension in reversed(extensions):
        try:
            extension.close()
        except Exception as e:
            logging.info(traceback.format_exc())

    extensions = []


def append_test_suites(suites: typing.Sequence[unittest.suite.TestSuite]) -> None:
    __test_suites.extend(suites)


def test_suites() -> typing.Sequence[unittest.suite.TestSuite]:
    return __test_suites
