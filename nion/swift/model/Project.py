# standard libraries
import logging
import typing
import uuid

# local libraries
from nion.swift.model import FileStorageSystem
from nion.utils import Event


class Project:
    """A project manages raw data items, display items, computations, data structures, and connections.

    Projects are stored in project indexes, which are files that describe how to find data and and tracks the other
    project relationships (display items, computations, data structures, connections).

    Projects manage reading, writing, and data migration.
    """

    def __init__(self, library_handler: FileStorageSystem.LibraryHandler):
        super().__init__()

        self.__library_handler = library_handler
        self.__storage_system = FileStorageSystem.FileStorageSystem(library_handler)

        self.item_loaded_event = Event.Event()
        self.item_unloaded_event = Event.Event()

    @property
    def project_reference(self) -> typing.Dict:
        return self.__library_handler.project_reference

    @property
    def _library_handler(self) -> FileStorageSystem.LibraryHandler:
        return self.__library_handler

    @property
    def _project_storage_system(self) -> FileStorageSystem.FileStorageSystem:
        return self.__storage_system

    def open(self) -> None:
        self.__storage_system.reset()  # this makes storage reusable during tests

    def close(self) -> None:
        pass

    def read_project(self) -> None:
        # first read the library (for deletions) and the library items from the primary storage systems
        logging.getLogger("loader").info(f"Loading project {self.__storage_system._library_handler.get_identifier()}")
        properties = self.__storage_system.read_library()
        for item_type in ("data_items", "display_items", "data_structures", "connections", "computations"):
            for item_d in properties.get(item_type, list()):
                self.item_loaded_event.fire(item_type, item_d, self.__storage_system)

    def restore_data_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        return self.__storage_system.restore_item(data_item_uuid)

    def prune(self) -> None:
        self.__storage_system.prune()

    def migrate_to_latest(self) -> None:
        self.__storage_system.migrate_to_latest()
        self.read_project()
