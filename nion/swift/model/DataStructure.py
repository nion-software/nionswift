# standard libraries
import copy
import typing
import weakref

# third party libraries

# local libraries
from nion.swift.model import Changes
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.utils import Event
from nion.utils import Observable

if typing.TYPE_CHECKING:
    from nion.swift.model import Project


class DataStructure(Observable.Observable, Persistence.PersistentObject):
    # regarding naming: https://en.wikipedia.org/wiki/Passive_data_structure
    def __init__(self, *, structure_type: str=None, source=None):
        super().__init__()
        self.about_to_cascade_delete_event = Event.Event()
        self.__properties = dict()
        self.__referenced_object_proxies = dict()
        self.define_type("data_structure")
        self.define_property("structure_type", structure_type)
        self.define_property("source_specifier", changed=self.__source_specifier_changed, key="source_uuid")
        # properties is handled explicitly
        self.data_structure_changed_event = Event.Event()
        self.referenced_objects_changed_event = Event.Event()
        self.__source_proxy = self.create_item_proxy(item=source)
        self.source_specifier = source.project.create_specifier(source).write() if source else None

    def close(self) -> None:
        self.__source_proxy.close()
        self.__source_proxy = None
        for referenced_proxy in self.__referenced_object_proxies.values():
            referenced_proxy.close()
        self.__referenced_object_proxies.clear()
        super().close()

    def __getattr__(self, name):
        properties = self.__dict__.get("_DataStructure__properties", dict())
        if name in properties:
            return properties[name]
        return super().__getattr__(name)

    def __setattr__(self, name, value):
        properties = self.__dict__.get("_DataStructure__properties", dict())
        if name in properties:
            if value is not None:
                self.set_property_value(name, value)
            else:
                self.remove_property_value(name)
        else:
            super().__setattr__(name, value)

    @property
    def project(self) -> "Project.Project":
        return typing.cast("Project.Project", self.container)

    def create_proxy(self) -> Persistence.PersistentObjectProxy:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(item_uuid=self.uuid, context_uuid=self.project.uuid)

    def prepare_cascade_delete(self) -> typing.List:
        cascade_items = list()
        self.about_to_cascade_delete_event.fire(cascade_items)
        return cascade_items

    def insert_model_item(self, container, name, before_index, item):
        if self.container:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> Changes.UndeleteLog:
        if self.container:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return Changes.UndeleteLog()

    def read_from_dict(self, properties):
        super().read_from_dict(properties)
        self.__properties = properties.get("properties")
        for property_name, value in self.__properties.items():
            self.__configure_reference_proxy(property_name, value, None)

    def __configure_reference_proxy(self, property_name, value, item):
        if isinstance(value, dict) and value.get("type") in {"data_item", "display_item", "data_source", "graphic", "structure"} and "uuid" in value:
            self.__referenced_object_proxies[property_name] = self.create_item_proxy(item_specifier=Persistence.PersistentObjectSpecifier.read(value["uuid"]), item=item)

    def write_to_dict(self):
        properties = super().write_to_dict()
        properties["properties"] = copy.deepcopy(self.__properties)
        return properties

    @property
    def source(self):
        return self.__source_proxy.item

    @source.setter
    def source(self, source):
        self.__source_proxy.item = source
        self.source_specifier = source.project.create_specifier(source).write() if source else None

    def __source_specifier_changed(self, name: str, d: typing.Dict) -> None:
        self.__source_proxy.item_specifier = Persistence.PersistentObjectSpecifier.read(d)

    def set_property_value(self, property: str, value) -> None:
        self.__properties[property] = value
        reference_object_proxy = self.__referenced_object_proxies.pop(property, None)
        if reference_object_proxy:
            reference_object_proxy.close()
        self.__configure_reference_proxy(property, value, None)
        self.data_structure_changed_event.fire(property)
        self.property_changed_event.fire(property)
        self._update_persistent_property("properties", self.__properties)

    def remove_property_value(self, property: str) -> None:
        if property in self.__properties:
            self.__properties.pop(property)
            reference_object_proxy = self.__referenced_object_proxies.pop(property, None)
            if reference_object_proxy:
                reference_object_proxy.close()
            self.data_structure_changed_event.fire(property)
            self.property_changed_event.fire(property)
            self._update_persistent_property("properties", self.__properties)

    def get_property_value(self, property: str, default_value=None):
        return self.__properties.get(property, default_value)

    def set_referenced_object(self, property: str, item) -> None:
        assert item is not None
        if item != self.get_referenced_object(property):
            object_type = "data_item" if isinstance(item, DataItem.DataItem) else None
            self.__properties[property] = get_object_specifier(item, object_type)
            reference_object_proxy = self.__referenced_object_proxies.pop(property, None)
            if reference_object_proxy:
                reference_object_proxy.close()
            self.__configure_reference_proxy(property, self.__properties[property], item)
            self.data_structure_changed_event.fire(property)
            self.property_changed_event.fire(property)
            self._update_persistent_property("properties", self.__properties)
            self.referenced_objects_changed_event.fire()

    def remove_referenced_object(self, property: str) -> None:
        self.remove_property_value(property)

    def get_referenced_object(self, property: str):
        return self.__referenced_object_proxies[property].item if property in self.__referenced_object_proxies else None

    @property
    def referenced_objects(self) -> typing.List:
        return list(referenced_object_proxy.item for referenced_object_proxy in self.__referenced_object_proxies.values())


def get_object_specifier(object, object_type: str = None, project=None) -> typing.Optional[typing.Dict]:
    # project is passed for testing only
    if isinstance(object, DataItem.DataItem):
        project = project or object.project
        specifier = project.create_specifier(object)
        d = {"version": 1, "type": object_type or "data_item", "uuid": str(specifier.item_uuid)}
        if specifier.context_uuid: d["context_uuid"] = str(specifier.context_uuid)
        return d
    if object and object_type in ("xdata", "display_xdata", "cropped_xdata", "cropped_display_xdata", "filter_xdata", "filtered_xdata"):
        assert isinstance(object, DisplayItem.DisplayDataChannel)
        project = project or object.project
        specifier = project.create_specifier(object)
        d = {"version": 1, "type": object_type, "uuid": str(specifier.item_uuid)}
        if specifier.context_uuid: d["context_uuid"] = str(specifier.context_uuid)
        return d
    if isinstance(object, DisplayItem.DisplayDataChannel):
        # should be "data_source" but requires file format change
        project = project or object.project
        specifier = project.create_specifier(object)
        d = {"version": 1, "type": "data_source", "uuid": str(specifier.item_uuid)}
        if specifier.context_uuid: d["context_uuid"] = str(specifier.context_uuid)
        return d
    elif isinstance(object, Graphics.Graphic):
        project = project or object.project
        specifier = project.create_specifier(object)
        d = {"version": 1, "type": "graphic", "uuid": str(specifier.item_uuid)}
        if specifier.context_uuid: d["context_uuid"] = str(specifier.context_uuid)
        return d
    elif isinstance(object, DataStructure):
        project = project or object.project
        specifier = project.create_specifier(object)
        d = {"version": 1, "type": "structure", "uuid": str(specifier.item_uuid)}
        if specifier.context_uuid: d["context_uuid"] = str(specifier.context_uuid)
        return d
    elif isinstance(object, DisplayItem.DisplayItem):
        project = project or object.project
        specifier = project.create_specifier(object)
        d = {"version": 1, "type": "display_item", "uuid": str(specifier.item_uuid)}
        if specifier.context_uuid: d["context_uuid"] = str(specifier.context_uuid)
        return d
    return None
