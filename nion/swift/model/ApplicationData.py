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


class Singleton(type):
    def __init__(cls, name, bases, dict):
        super(Singleton, cls).__init__(name, bases, dict)
        cls.instance = None

    def __call__(cls, *args, **kw):
        if cls.instance is None:
            cls.instance = super(Singleton, cls).__call__(*args, **kw)
        return cls.instance


class ApplicationData(metaclass=Singleton):
    """Application data is a singleton that stores application data."""

    def __init__(self):
        self.__lock = threading.RLock()
        self.__file_path = None
        self.__data = None
        self.data_changed_event = Event.Event()

    @property
    def file_path(self) -> pathlib.Path:
        return self.__file_path

    @file_path.setter
    def file_path(self, value: pathlib.Path) -> None:
        self.__file_path = value

    @property
    def data(self) -> typing.Dict:
        with self.__lock:
            data_changed = self.__read_data()
            result = copy.deepcopy(self.__data) if self.__data else dict()
        if data_changed:
            self.data_changed_event.fire()
        return result

    @data.setter
    def data(self, value: typing.Dict) -> None:
        with self.__lock:
            assert value is not None
            self.__data = value
            self.__write_data()
        self.data_changed_event.fire()

    def __read_data(self) -> bool:
        if self.__data is None and self.__file_path and self.__file_path.exists():
            with open(self.__file_path) as f:
                self.__data = json.load(f)
                return True
        return False

    def __write_data(self):
        if self.__file_path:
            with Utility.AtomicFileWriter(self.__file_path) as fp:
                json.dump(self.__data, fp, skipkeys=True, indent=4)


def set_file_path(file_path: pathlib.Path) -> None:
    ApplicationData().file_path = file_path


def get_data() -> typing.Dict:
    return ApplicationData().data


def set_data(data: typing.Dict) -> None:
    ApplicationData().data = data


#

class SessionMetadata(metaclass=Singleton):
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

def get_session_metadata_model() -> StructuredModel.RecordModel:
    return SessionMetadata().model

def get_session_metadata_dict() -> typing.Dict:
    return SessionMetadata().model.to_dict_value()
