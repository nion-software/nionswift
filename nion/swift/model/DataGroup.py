from __future__ import annotations

# standard libraries
import collections
import gettext
import typing
import uuid

# third party libraries
# None

# local libraries
from nion.swift.model import DisplayItem
from nion.swift.model import Persistence

if typing.TYPE_CHECKING:
    from nion.swift.model import Project

_SpecifierType = Persistence._SpecifierType
_SpecifierDictType = Persistence._SpecifierDictType


_ = gettext.gettext


"""

    Group layout.
    Live. Live acquisition items.
    Library. Static items.

    *   The user can edit/delete the Library group, and create additional top level groups.
    However, at least one group in addition to the Live group must always be present.
    *   The user cannot delete the live group.
    *   The user cannot add/delete items from the Live group.
    *   Groups can be re-ordered, but the Live group is always first.
    *   New items are put in the first group after Live.

    *   NOTES
    Groups can contain child groups and data items.

    One design option is to have the document controller hold a single data group.
    This has the advantage of making access very uniform. However, this also makes
    it very easy for the user to "lose" items at the top level, which they might not
    see unless they selected the topmost group.

    Another design option is to have the document controller hold a list of data
    groups. This is more complex structure, but makes it easier for the user to
    understand the structure.

    Smart Groups

    Smart groups work on sibling data groups (aka the data items in the smart group's
    container). A smart group at the top level of groups will be able to filter
    and sort data items contained in other top level groups.
    Is there a need for smart groups anywhere except at the top level?

    - (A1a: 1, A1b: 1, A1b1: 2, A1b1a: 2, A1b2: 1, B1: 1, B1a: 1) [0]
    Smart Group [-]
    Group A (A1a: 1, A1b: 1, A1b1: 1, A1b1a: 1, A1b2: 1) [-]
    Group A1 (A1a: 1, A1b: 1, A1b1: 1, A1b1a: 1, A1b2: 1) [A]
    Data Item A1a () [A1]
    Data Item A1b (A1b1: 1, A1b1a: 1, A1b2: 1) [A1]
    Data Item A1b1 (A1b1a: 1 [A1b]
    Data Item A1b1a () [A1b1]
    Data Item A1b2 () [A1b]
    Group B (B1: 1, B1a: 1, A1b1: 1, A1b1a: 1) [-]
    Data Item B1 (B1a: 1) [B]
    Data Item B1a [B1]
    Data Item A1b1 (A1b1a: 1) [B, A1b]
    Data Item A1b1a [A1b1]

    Data item A1b1b gets added to A1b1. A1b1 counted_display_items gets updated, then tells its containers B, A1b
    that they have been updated. B, A1b counted_display_items get updated, then tell their containers, etc.
    When each group gets the counted_display_items_updated message, it tells any smart container children
    that they need to re-filter.

    Data item A2 gets added to Group A.

    """


class UuidsToStringsConverter:
    def convert(self, value: typing.List[uuid.UUID]) -> typing.List[str]:
        return [str(uuid_) for uuid_ in value]

    def convert_back(self, value: typing.List[str]) -> typing.List[uuid.UUID]:
        return [uuid.UUID(uuid_str) for uuid_str in value]


class DataGroup(Persistence.PersistentObject):

    def __init__(self) -> None:
        super().__init__()
        self.define_type("data_group")
        self.define_property("title", _("Untitled"), hidden=True, validate=self.__validate_title, changed=self.__property_changed)
        self.define_property("display_item_specifiers", list(), hidden=True, validate=self.__validate_display_item_specifiers, changed=self.__property_changed, key="display_item_references")
        self.define_relationship("data_groups", data_group_factory, insert=self.__insert_data_group, remove=self.__remove_data_group, hidden=True)
        self.__lookup_display_item: typing.Optional[typing.Callable[[_SpecifierType], typing.Optional[DisplayItem.DisplayItem]]] = None
        self.__display_items: typing.List[DisplayItem.DisplayItem] = list()
        # Python 3.9+: typed counter
        self.__counted_display_items = collections.Counter()  # type: ignore

    def __str__(self) -> str:
        return self.title

    @property
    def title(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("title"))

    @title.setter
    def title(self, value: str) -> None:
        self._set_persistent_property_value("title", value)

    @property
    def display_item_specifiers(self) -> typing.List[_SpecifierType]:
        return typing.cast(typing.List[_SpecifierType], self._get_persistent_property_value("display_item_specifiers"))

    @display_item_specifiers.setter
    def display_item_specifiers(self, value: typing.Sequence[_SpecifierType]) -> None:
        self._set_persistent_property_value("display_item_specifiers", list(value))

    @property
    def data_groups(self) -> typing.Sequence[DataGroup]:
        return typing.cast(typing.Sequence[DataGroup], self._get_relationship_values("data_groups"))

    @property
    def project(self) -> Project.Project:
        if isinstance(self.container, self.__class__):
            return self.container.project
        return typing.cast("Project.Project", self.container)

    def create_proxy(self) -> Persistence.PersistentObjectProxy:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(item_uuid=self.uuid)

    def __validate_title(self, value: typing.Any) -> str:
        return str(value) if value is not None else str()

    def __validate_display_item_specifiers(self, display_item_specifiers: typing.Sequence[_SpecifierType]) -> typing.Sequence[_SpecifierType]:
        # remove duplicates
        new_display_item_specifiers = list()
        for display_item_specifier in display_item_specifiers:
            if display_item_specifier not in new_display_item_specifiers:
                new_display_item_specifiers.append(display_item_specifier)
        return new_display_item_specifiers

    def __property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)

    def connect_display_items(self, lookup_display_item: typing.Callable[[_SpecifierType], typing.Optional[DisplayItem.DisplayItem]]) -> None:
        for data_group in self.data_groups:
            data_group.connect_display_items(lookup_display_item)
        display_items: typing.List[DisplayItem.DisplayItem] = list()
        for display_item_specifier in self.display_item_specifiers:
            display_item = lookup_display_item(display_item_specifier)
            if display_item:
                display_items.append(display_item)
        self.__display_items = display_items
        self.__lookup_display_item = lookup_display_item

    def disconnect_display_items(self) -> None:
        for data_group in self.data_groups:
            data_group.disconnect_display_items()
        self.__lookup_display_item = None

    def append_display_item(self, display_item: DisplayItem.DisplayItem) -> None:
        self.insert_display_item(len(self.__display_items), display_item)

    def insert_display_item(self, before_index: int, display_item: DisplayItem.DisplayItem) -> None:
        assert display_item not in self.__display_items
        self.__display_items.insert(before_index, display_item)
        self.notify_insert_item("display_items", display_item, before_index)
        self.update_counted_display_items(collections.Counter([display_item]))
        display_item_specifiers = self.display_item_specifiers
        display_item_specifier = display_item.project.create_specifier(display_item).write()
        assert display_item_specifier is not None
        display_item_specifiers.insert(before_index, display_item_specifier)
        self.display_item_specifiers = display_item_specifiers
        self.notify_property_changed("display_item_specifiers")

    def remove_display_item(self, display_item: DisplayItem.DisplayItem) -> None:
        index = self.__display_items.index(display_item)
        self.__display_items.remove(display_item)
        self.subtract_counted_display_items(collections.Counter([display_item]))
        self.notify_remove_item("display_items", display_item, index)
        display_item_specifiers = self.display_item_specifiers
        display_item_specifiers.pop(index)
        self.display_item_specifiers = display_item_specifiers
        self.notify_property_changed("display_item_specifiers")

    @property
    def display_items(self) -> typing.Tuple[DisplayItem.DisplayItem, ...]:
        return tuple(self.__display_items)

    def append_data_group(self, data_group: DataGroup) -> None:
        self.insert_data_group(len(self.data_groups), data_group)

    def insert_data_group(self, before_index: int, data_group: DataGroup) -> None:
        self.insert_item("data_groups", before_index, data_group)

    def remove_data_group(self, data_group: DataGroup) -> None:
        self.remove_item("data_groups", data_group)

    def __insert_data_group(self, name: str, before_index: int, data_group: DataGroup) -> None:
        if self.__lookup_display_item:
            data_group.connect_display_items(self.__lookup_display_item)
        self.update_counted_display_items(data_group.counted_display_items)
        self.notify_insert_item("data_groups", data_group, before_index)

    def __remove_data_group(self, name: str, index: int, data_group: DataGroup) -> None:
        data_group.disconnect_display_items()
        self.subtract_counted_display_items(data_group.counted_display_items)
        self.notify_remove_item("data_groups", data_group, index)

    @property
    def counted_display_items(self) -> collections.Counter[DisplayItem.DisplayItem]:
        return self.__counted_display_items

    def update_counted_display_items(self, counted_display_items: collections.Counter[DisplayItem.DisplayItem]) -> None:
        self.__counted_display_items.update(counted_display_items)

    def subtract_counted_display_items(self, counted_display_items: collections.Counter[DisplayItem.DisplayItem]) -> None:
        self.__counted_display_items.subtract(counted_display_items)
        self.__counted_display_items += collections.Counter()  # strip empty items


class _DataGroupContainer(typing.Protocol):

    @property
    def data_groups(self) -> typing.Sequence[DataGroup]: raise NotImplementedError()

    @property
    def display_items(self) -> typing.Sequence[DisplayItem.DisplayItem]: raise NotImplementedError()


# return a generator for all data groups and child data groups in container
def get_flat_data_group_generator_in_container(container: _DataGroupContainer) -> typing.Iterator[DataGroup]:
    for data_group in container.data_groups:
        yield data_group
        for child_data_group in get_flat_data_group_generator_in_container(data_group):
            yield child_data_group


# return a generator for all data items, child data items, and data items in child groups in container
def get_flat_display_item_generator_in_container(container: _DataGroupContainer) -> typing.Iterator[DisplayItem.DisplayItem]:
    if hasattr(container, "display_items"):
        for display_item in container.display_items:
            yield display_item
    if hasattr(container, "data_groups"):
        for data_group in container.data_groups:
            for display_item in get_flat_display_item_generator_in_container(data_group):
                yield display_item


# Return the data_group matching name that is the descendent of the container.
def get_data_group_in_container_by_title(container: _DataGroupContainer, data_group_title: str) -> typing.Optional[DataGroup]:
    for data_group in container.data_groups:
        if data_group.title == data_group_title:
            return data_group
    return None


# Return the display_item matching name that is the descendent of the container.
def get_display_item_in_container_by_title(container: _DataGroupContainer, display_item_title: str) -> typing.Optional[DisplayItem.DisplayItem]:
    for display_item in container.display_items:
        if display_item.title == display_item_title:
            return display_item
    return None


# Return the data_group matching name that is the descendent of the container.
def get_data_group_in_container_by_uuid(container: _DataGroupContainer, data_group_uuid: uuid.UUID) -> typing.Optional[DataGroup]:
    for data_group in container.data_groups:
        if data_group.uuid == data_group_uuid:
            return data_group
    return None


# Return the display_item matching name that is the descendent of the container.
def get_display_item_in_container_by_uuid(container: _DataGroupContainer, display_item_uuid: uuid.UUID) -> typing.Optional[DisplayItem.DisplayItem]:
    for display_item in container.display_items:
        if display_item.uuid == display_item_uuid:
            return display_item
    return None


def data_group_factory(lookup_id: typing.Callable[[str], str]) -> DataGroup:
    return DataGroup()
