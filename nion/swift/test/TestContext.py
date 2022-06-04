# system libraries
import typing
import unittest
import uuid

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import Cache
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import FileStorageSystem
from nion.swift.model import HDF5Handler
from nion.swift.model import NDataHandler
from nion.swift.model import Persistence
from nion.swift.model import Profile
from nion.ui import TestUI
from nion.utils import Event
from nion.utils import ReferenceCounting


def begin_leaks() -> None:
    Cache.DbStorageCache.count = 0
    NDataHandler.NDataHandler.count = 0
    HDF5Handler.HDF5Handler.count = 0
    HDF5Handler._file_manager._clear()
    Persistence.PersistentObjectProxy.count = 0
    Persistence.PersistentObjectReference.count = 0
    Persistence.PersistentObject.count = 0
    ReferenceCounting.ReferenceCounted.count = 0
    DataItem.DataItem._data_count = 0


def end_leaks(test_case: unittest.TestCase) -> None:
    test_case.assertEqual(0, Cache.DbStorageCache.count)
    test_case.assertEqual(0, NDataHandler.NDataHandler.count)
    test_case.assertEqual(0, HDF5Handler.HDF5Handler.count)
    test_case.assertEqual(0, HDF5Handler._file_manager._open_count)
    test_case.assertEqual(0, len(DocumentModel.MappedItemManager().item_map.items()))
    test_case.assertEqual(0, Persistence.PersistentObjectProxy.count)
    test_case.assertEqual(0, Persistence.PersistentObjectReference.count)
    test_case.assertEqual(0, Persistence.PersistentObject.count)
    test_case.assertEqual(0, ReferenceCounting.ReferenceCounted.count)
    test_case.assertEqual(0, DisplayItem.DisplayValues._count)
    # the next assert is very aggressive, particularly difficult to satisfy with async/threading (histogram).
    # test_case.assertEqual(0, DataItem.DataItem._data_count)


def convert_tuples_to_lists(i: typing.Any) -> typing.Any:
    itype = type(i)
    if itype == dict:
        return {k: convert_tuples_to_lists(v) for k, v in i.items()}
    elif itype == list or itype == tuple:
        return [convert_tuples_to_lists(v) for v in i]
    return i


class MemoryProfileContext:
    # used for testing

    def __init__(self) -> None:
        self.storage_cache = Cache.DictStorageCache()

        self.profile_properties = dict()
        self.__storage_system = FileStorageSystem.MemoryPersistentStorageSystem(library_properties=self.profile_properties)
        self.__storage_system.load_properties()

        # these contain the data for each project.
        self.x_project_properties = dict()
        self.x_data_properties_map = dict()
        self.x_data_map = dict()
        self.x_trash_map = dict()

        # these contain the data for the first created project. they also facilitate legacy project testing.
        self.project_uuid = None
        self.project_properties = None
        self.data_properties_map = None
        self.data_map = None
        self.trash_map = None

        self._test_data_read_event = Event.Event()
        self.__profile = None

        self.__items_exit = list()

    def reset_profile(self):
        self.__profile = None
        self.profile_properties.clear()
        self.project_uuid = None
        self.project_properties = None
        self.data_properties_map = None
        self.data_map = None
        self.trash_map = None

    def reload(self):
        self.profile_properties = convert_tuples_to_lists(self.profile_properties)
        self.x_project_properties = convert_tuples_to_lists(self.x_project_properties)
        self.x_data_properties_map = convert_tuples_to_lists(self.x_data_properties_map)
        self.x_data_map = convert_tuples_to_lists(self.x_data_map)
        self.x_trash_map = convert_tuples_to_lists(self.x_trash_map)

    def create_legacy_project(self) -> None:
        """Create a legacy project."""
        self.project_uuid = uuid.uuid4()
        self.project_properties = self.x_project_properties[self.project_uuid] = {"uuid": str(self.project_uuid)}
        self.data_properties_map = self.x_data_properties_map[self.project_uuid] = dict()
        self.data_map = self.x_data_map[self.project_uuid] = dict()
        self.trash_map = self.x_trash_map[self.project_uuid] = dict()

    def create_profile(self, add_project: bool = True) -> Profile.Profile:
        if not self.__profile:
            library_properties = {"version": FileStorageSystem.PROFILE_VERSION}
            storage_system = self.__storage_system
            storage_system.set_library_properties(library_properties)
            profile = Profile.Profile(storage_system=storage_system, storage_cache=self.storage_cache)
            profile.storage_system = storage_system
            profile.profile_context = self
            if add_project:
                add_project_memory(profile, self.project_uuid)
            self.__profile = profile
            self.__items_exit.append(profile.close)
            return profile
        else:
            storage_system = self.__storage_system
            storage_system.load_properties()
            profile = Profile.Profile(storage_system=storage_system, storage_cache=self.storage_cache)
            profile.storage_system = storage_system
            profile.profile_context = self
            self.__items_exit.append(profile.close)
            return profile

    @property
    def profile(self) -> typing.Optional[Profile.Profile]:
        return self.__profile

    def create_document_model(self, *, project_index: int = 0, auto_close: bool = True) -> DocumentModel.DocumentModel:
        profile = self.create_profile()
        profile.read_profile()
        project_reference = profile.project_references[project_index]
        profile.read_project(project_reference)
        document_model = project_reference.document_model
        document_model._profile_for_test = profile
        if auto_close:
            document_model.add_ref()
            self.__items_exit.append(document_model.remove_ref)
        return document_model

    def create_document_controller(self, *, auto_close: bool = True) -> DocumentController.DocumentController:
        document_model = self.create_document_model(auto_close=False)
        document_controller = DocumentController.DocumentController(TestUI.UserInterface(), document_model, workspace_id="library")
        if auto_close:
            self.__items_exit.append(document_controller.close)
        return document_controller

    def create_secondary_document_controller(self, document_model: DocumentModel.DocumentModel, *, auto_close: bool = True) -> DocumentController.DocumentController:
        document_controller = DocumentController.DocumentController(TestUI.UserInterface(), document_model, workspace_id="library")
        if auto_close:
            self.__items_exit.append(document_controller.close)
        return document_controller

    def create_document_controller_with_application(self) -> DocumentController.DocumentController:
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = self.create_document_model(auto_close=False)
        document_controller = app.create_document_controller(document_model, "library")
        self.__items_exit.append(document_controller.close)
        self.__app = app  # hold a reference
        app._set_document_model(document_model)  # required to allow API to find document model
        return document_controller

    def create_application(self) -> Application.Application:
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        self.__app = app  # hold a reference
        return app

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        self.close()

    def close(self) -> None:
        for item in reversed(self.__items_exit):
            item()
        self.__items_exit = list()
        self.__app = None


class MemoryProjectReference(Profile.ProjectReference):
    type = "project_memory"

    def __init__(self, d: typing.Dict = None, make_storage_error: bool = False):
        super().__init__(self.__class__.type)
        self.__d = d or dict()
        self.__make_storage_error = make_storage_error

    @property
    def project_reference_parts(self) -> typing.Tuple[str]:
        return ("memory",)

    def make_storage(self, profile_context: typing.Optional[MemoryProfileContext]) -> typing.Optional[FileStorageSystem.ProjectStorageSystem]:
        if self.__make_storage_error:
            raise Exception("make_storage_error")
        return FileStorageSystem.make_memory_project_storage_system(profile_context, self.project_uuid, self.__d)

    def _upgrade_project_storage_system(self, project_storage_system: FileStorageSystem.ProjectStorageSystem) -> Profile.ProjectReference:
        new_project_reference = MemoryProjectReference()
        new_project_reference.project_uuid = uuid.uuid4()
        return new_project_reference


def create_memory_context():
    return MemoryProfileContext()


def add_project_memory(profile: Profile.Profile, _uuid: uuid.UUID = None, load: bool = True, d: typing.Dict = None, make_storage_error: bool = False, make_uuid_error: bool = False) -> Profile.ProjectReference:
    if make_uuid_error:
        d = d or dict()
        d["uuid"] = 999
    project_reference = MemoryProjectReference(d, make_storage_error)
    project_reference.project_uuid = _uuid or uuid.uuid4()
    return profile.add_project_reference(project_reference, load)


def project_reference_factory(type: typing.Type) -> typing.Optional[Profile.ProjectReference]:
    if type == MemoryProjectReference.type:
        return MemoryProjectReference()
    return None


Profile.project_reference_factory_hook = project_reference_factory
