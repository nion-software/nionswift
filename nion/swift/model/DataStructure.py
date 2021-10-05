from __future__ import annotations

# standard libraries
import copy
import typing

# third party libraries

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.swift.model import Schema
from nion.utils import Event

if typing.TYPE_CHECKING:
    from nion.swift.model import Project


class DataStructure(Persistence.PersistentObject):
    entity_types:typing.Dict[str, Schema.EntityType] = dict()
    entity_names:typing.Dict[str, str] = dict()
    entity_package_names:typing.Dict[str, str] = dict()

    # regarding naming: https://en.wikipedia.org/wiki/Passive_data_structure
    def __init__(self, *, structure_type: typing.Optional[str] = None, source: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__()
        self.__properties: typing.Dict[str, typing.Any] = dict()
        self.__referenced_object_proxies: typing.Dict[str, Persistence.PersistentObjectProxy] = dict()
        self.define_type("data_structure")
        self.define_property("structure_type", structure_type, changed=self.__structure_type_changed)
        self.define_property("source_specifier", changed=self.__source_specifier_changed, key="source_uuid")
        # properties is handled explicitly
        self.data_structure_changed_event = Event.Event()
        self.data_structure_objects_changed_event = Event.Event()
        self.__source_reference = self.create_item_reference(item=source)
        self.source_specifier = source.project.create_specifier(source).write() if source else None
        self.__entity: typing.Optional[Schema.Entity] = None
        self.__entity_property_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__create_entity()

    def close(self) -> None:
        if self.__entity_property_changed_event_listener:
            self.__entity_property_changed_event_listener.close()
            self.__entity_property_changed_event_listener = typing.cast(Event.EventListener, None)
        if self.__entity:
            self.__entity.close()
            self.__entity = None
        for referenced_proxy in self.__referenced_object_proxies.values():
            referenced_proxy.close()
        self.__referenced_object_proxies.clear()
        super().close()

    @classmethod
    def register_entity(cls, entity_type: Schema.EntityType, *, entity_name: typing.Optional[str] = None, entity_package_name: typing.Optional[str] = None, **kwargs: typing.Any) -> None:
        DataStructure.entity_types[entity_type.entity_id] = entity_type
        if entity_name:
            DataStructure.entity_names[entity_type.entity_id] = entity_name
        if entity_package_name:
            DataStructure.entity_package_names[entity_type.entity_id] = entity_package_name

    @classmethod
    def unregister_entity(cls, entity_type: Schema.EntityType) -> None:
        DataStructure.entity_types.pop(entity_type.entity_id)
        DataStructure.entity_names.pop(entity_type.entity_id, None)
        DataStructure.entity_package_names.pop(entity_type.entity_id, None)

    def __getattr__(self, name: str) -> typing.Any:
        properties = self.__dict__.get("_DataStructure__properties", dict())
        if name in properties:
            return properties[name]
        return super().__getattr__(name)

    def __setattr__(self, name: str, value: typing.Any) -> None:
        properties = self.__dict__.get("_DataStructure__properties", dict())
        if name in properties:
            if value is not None:
                self.set_property_value(name, value)
            else:
                self.remove_property_value(name)
        else:
            super().__setattr__(name, value)

    @property
    def project(self) -> Project.Project:
        return typing.cast("Project.Project", self.container)

    def create_proxy(self) -> Persistence.PersistentObjectProxy:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(item_uuid=self.uuid)

    def read_from_dict(self, properties: Persistence.PersistentDictType) -> None:
        super().read_from_dict(properties)
        self.__properties = typing.cast(typing.Dict[str, typing.Any], properties.get("properties"))
        for property_name, value in self.__properties.items():
            self.__configure_reference_proxy(property_name, value, None)
        self.__create_entity()

    def __create_entity(self) -> None:
        if self.__entity_property_changed_event_listener:
            self.__entity_property_changed_event_listener.close()
            self.__entity_property_changed_event_listener = typing.cast(Event.EventListener, None)
            if self.__entity:
                self.__entity.close()
            self.__entity = None

        if self.structure_type in DataStructure.entity_types:
            self.__entity = DataStructure.entity_types[self.structure_type].create(typing.cast(Schema.EntityContext, self.persistent_object_context), self.__properties)

            def entity_property_changed(name: str) -> None:
                if name != "type":
                    value = getattr(self.__entity, name)
                    self.__properties[name] = value
                    reference_object_proxy = self.__referenced_object_proxies.pop(name, None)
                    if reference_object_proxy:
                        reference_object_proxy.close()
                    self.__configure_reference_proxy(name, value, None)
                    self.data_structure_changed_event.fire(name)
                    self.property_changed_event.fire(name)
                self._update_persistent_property("properties", self.__properties)

            self.__entity_property_changed_event_listener = self.__entity.property_changed_event.listen(entity_property_changed)

    def __configure_reference_proxy(self, property_name: str, value: typing.Any, item: typing.Optional[Persistence.PersistentObject]) -> None:
        if isinstance(value, dict) and value.get("type") in {"data_item", "display_item", "data_source", "graphic", "structure"} and "uuid" in value:
            self.__referenced_object_proxies[property_name] = self.create_item_proxy(item_specifier=Persistence.PersistentObjectSpecifier.read(value["uuid"]), item=item)

    def write_to_dict(self) -> Persistence.PersistentDictType:
        properties = super().write_to_dict()
        properties["properties"] = copy.deepcopy(self.__properties)
        return properties

    @property
    def source(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__source_reference.item

    @source.setter
    def source(self, source: typing.Optional[Persistence.PersistentObject]) -> None:
        self.__source_reference.item = source
        self.source_specifier = source.project.create_specifier(source).write() if source else None

    @property
    def entity(self) -> typing.Optional[Schema.Entity]:
        return self.__entity

    def __structure_type_changed(self, name: str, structure_type: str) -> None:
        self.__create_entity()
        self.property_changed_event.fire("structure_type")

    def __source_specifier_changed(self, name: str, d: Persistence._SpecifierType) -> None:
        self.__source_reference.item_specifier = Persistence.PersistentObjectSpecifier.read(d)

    def set_property_value(self, property: str, value: typing.Any) -> None:
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

    def get_property_value(self, property: str, default_value: typing.Any = None) -> typing.Any:
        return self.__properties.get(property, default_value)

    def set_referenced_object(self, property: str, item: typing.Any) -> None:
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
            self.data_structure_objects_changed_event.fire()

    def remove_referenced_object(self, property: str) -> None:
        self.remove_property_value(property)

    def get_referenced_object(self, property: str) -> typing.Any:
        return self.__referenced_object_proxies[property].item if property in self.__referenced_object_proxies else None

    @property
    def referenced_objects(self) -> typing.List[typing.Optional[Persistence.PersistentObject]]:
        return list(referenced_object_proxy.item for referenced_object_proxy in self.__referenced_object_proxies.values())


def get_object_specifier(object: typing.Optional[Persistence.PersistentObject], object_type: typing.Optional[str] = None,
                         project: typing.Optional[Project.Project] = None) -> typing.Optional[Persistence.PersistentDictType]:
    # project is passed for testing only
    if isinstance(object, DataItem.DataItem):
        project = project or object.project
        specifier = project.create_specifier(object) if project else None
        specifier_uuid = specifier.item_uuid if specifier else object.uuid
        d = {"version": 1, "type": object_type or "data_item", "uuid": str(specifier_uuid)}
        return d
    if object and object_type in ("xdata", "display_xdata", "cropped_xdata", "cropped_display_xdata", "filter_xdata", "filtered_xdata"):
        assert isinstance(object, DisplayItem.DisplayDataChannel)
        project = project or object.project
        specifier = project.create_specifier(object) if project else None
        specifier_uuid = specifier.item_uuid if specifier else object.uuid
        d = {"version": 1, "type": object_type, "uuid": str(specifier_uuid)}
        return d
    if isinstance(object, DisplayItem.DisplayDataChannel):
        # should be "data_source" but requires file format change
        project = project or object.project
        specifier = project.create_specifier(object) if project else None
        specifier_uuid = specifier.item_uuid if specifier else object.uuid
        d = {"version": 1, "type": "data_source", "uuid": str(specifier_uuid)}
        return d
    elif isinstance(object, Graphics.Graphic):
        project = project or object.project
        specifier = project.create_specifier(object) if project else None
        specifier_uuid = specifier.item_uuid if specifier else object.uuid
        d = {"version": 1, "type": "graphic", "uuid": str(specifier_uuid)}
        return d
    elif isinstance(object, DataStructure):
        project = project or object.project
        specifier = project.create_specifier(object) if project else None
        specifier_uuid = specifier.item_uuid if specifier else object.uuid
        d = {"version": 1, "type": "structure", "uuid": str(specifier_uuid)}
        return d
    elif isinstance(object, DisplayItem.DisplayItem):
        project = project or object.project
        specifier = project.create_specifier(object) if project else None
        specifier_uuid = specifier.item_uuid if specifier else object.uuid
        d = {"version": 1, "type": "display_item", "uuid": str(specifier_uuid)}
        return d
    return None
