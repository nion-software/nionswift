"""
Stores application data.
"""

# standard libraries
import copy
import json
import pathlib
import threading
import typing

# third party libraries
from nion.swift.model import Utility
from nion.utils import Event
from nion.utils import StructuredModel


class ApplicationData:
    """Application data is a singleton that stores application data."""

    def __init__(self, file_path: typing.Optional[pathlib.Path] = None):
        self.__lock = threading.RLock()
        self.__file_path = file_path
        self.__data_dict: typing.Optional[typing.Dict] = None
        self.data_changed_event = Event.Event()

    @property
    def file_path(self) -> typing.Optional[pathlib.Path]:
        return self.__file_path

    @file_path.setter
    def file_path(self, value: pathlib.Path) -> None:
        self.__file_path = value

    def get_data_dict(self) -> typing.Dict:
        with self.__lock:
            data_changed = self.__read_data_dict()
            result = copy.deepcopy(self.__data_dict) if self.__data_dict else dict()
        if data_changed:
            self.data_changed_event.fire()
        return result

    def set_data_dict(self, d: typing.Dict) -> None:
        with self.__lock:
            assert d is not None
            self.__data_dict = d
            self.__write_data_dict()
        self.data_changed_event.fire()

    def __read_data_dict(self) -> bool:
        if self.__data_dict is None and self.__file_path and self.__file_path.exists():
            with open(self.__file_path) as f:
                self.__data_dict = json.load(f)
                return True
        return False

    def __write_data_dict(self):
        if self.__file_path:
            with Utility.AtomicFileWriter(self.__file_path) as fp:
                json.dump(self.__data_dict, fp, skipkeys=True, indent=4)


__application_data = ApplicationData()


def set_file_path(file_path: pathlib.Path) -> None:
    __application_data.file_path = file_path


def get_data() -> typing.Dict:
    return __application_data.get_data_dict()


def set_data(d: typing.Dict) -> None:
    __application_data.set_data_dict(d)


#

class SessionMetadata:
    """Session data is a singleton that stores application data via the ApplicationData singleton."""

    def __init__(self):
        site_field = StructuredModel.define_field("site", StructuredModel.STRING)
        instrument_field = StructuredModel.define_field("instrument", StructuredModel.STRING)
        task_field = StructuredModel.define_field("task", StructuredModel.STRING)
        microscopist_field = StructuredModel.define_field("microscopist", StructuredModel.STRING)
        sample_field = StructuredModel.define_field("sample", StructuredModel.STRING)
        sample_area_field = StructuredModel.define_field("sample_area", StructuredModel.STRING)
        schema = StructuredModel.define_record("SessionMetadata", [site_field, instrument_field, task_field, microscopist_field, sample_field, sample_area_field])

        self.__model = StructuredModel.build_model(schema, value=get_data().get("session_metadata", dict()))

        def model_changed():
            data = get_data()
            data["session_metadata"] = self.__model.to_dict_value()
            set_data(data)

        self.__model_changed_listener = self.__model.model_changed_event.listen(model_changed)

    @property
    def model(self) -> StructuredModel.RecordModel:
        return self.__model

__session_metadata = SessionMetadata()

def get_session_metadata_model() -> StructuredModel.RecordModel:
    return __session_metadata.model

def get_session_metadata_dict() -> typing.Dict[str, typing.Any]:
    return dict(typing.cast(typing.Mapping[str, typing.Any], __session_metadata.model.to_dict_value()))
