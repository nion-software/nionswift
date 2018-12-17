# standard libraries
import typing
import uuid

# local libraries
from nion.swift.model import Cache
from nion.swift.model import MemoryStorageSystem
from nion.utils import Persistence


class Profile:

    def __init__(self, storage_system=None, storage_cache=None, ignore_older_files=False):
        self.__storage_system = storage_system if storage_system else MemoryStorageSystem.MemoryStorageSystem()
        self.__storage_system.reset()  # this makes storage reusable during tests
        self.__ignore_older_files = ignore_older_files
        self.storage_cache = storage_cache if storage_cache else Cache.DictStorageCache()
        # the persistent object context allows reading/writing of objects to the persistent storage specific to them.
        # there is a single shared object context per profile.
        self.persistent_object_context = Persistence.PersistentObjectContext()

    def connect_document_model(self, document_model) -> None:
        self.persistent_object_context._set_persistent_storage_for_object(document_model, self.__storage_system)

    def validate_uuid_and_version(self, document_model, uuid_: uuid.UUID, version: int) -> None:
        self.__storage_system.set_property(document_model, "uuid", str(uuid_))
        self.__storage_system.set_property(document_model, "version", version)

    def restore_data_item(self, data_item_uuid: uuid.UUID) -> typing.Tuple[typing.Optional[dict], bool]:
        return self.__storage_system.restore_item(data_item_uuid)

    def prune(self):
        self.__storage_system.prune()

    def read_library(self) -> typing.Dict:
        # first read the library (for deletions) and the library items from the primary storage systems
        return self.__storage_system.read_library(self.__ignore_older_files)
