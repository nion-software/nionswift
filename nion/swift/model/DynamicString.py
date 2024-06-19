from __future__ import annotations

# standard libraries
import collections
import copy
import datetime
import functools
import gettext
import typing
import weakref

# local libraries
from nion.data import DataAndMetadata
from nion.swift.model import Persistence
from nion.utils import Event
from nion.utils import Observable
from nion.utils.ReferenceCounting import weak_partial
from nion.utils import Registry
from nion.utils import Stream

_ = gettext.gettext

if typing.TYPE_CHECKING:
    from nion.swift.model import DisplayItem


class DynamicString:
    def __init__(self) -> None:
        self.string_stream = Stream.ValueStream[str]()
        self.persistence_stream = Stream.ValueStream[Persistence.PersistentDictType]()

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> DynamicString:
        raise NotImplementedError()

    # called by the owner of the dynamic string to connect the slugs to the observed item.
    def connect_item(self, item: typing.Optional[Observable.Observable]) -> None:
        pass


class DynamicStringSlug(Stream.ValueStream[str]):
    """A dynamic string slug is a stream of strings that updates dynamically by observing metadata.

    Subclasses should observe their targets and update the str value by setting the value property in
    response to changes.

    Subclasses can utilize the _item_stream and _display_item_stream properties when configuring
    observation.
    """
    def __init__(self, slug_id: str, default_value: typing.Optional[str] = None) -> None:
        super().__init__(default_value or str())
        self.slug_id = slug_id

        # the item stream is the specific item being observed.
        self._item_stream = Stream.ValueStream[Observable.Observable]()

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> DynamicStringSlug:
        return DynamicStringSlug(self.slug_id, self.value)

    def write_to_dict(self) -> Persistence.PersistentDictType:
        d = {"type": self.slug_id}
        if self.value:
            d["value"] = self.value
        return d

    # called by the containing dynamic string during setup.
    def set_item(self, item: typing.Optional[Observable.Observable]) -> None:
        self._item_stream.value = item


ItemPropertySlugType = typing.TypeVar("ItemPropertySlugType")


class ItemPropertySlug(DynamicStringSlug, typing.Generic[ItemPropertySlugType]):
    """A dynamic string slug that observes a property on an item and converts it to a string."""
    def __init__(self,
                 property: str,
                 convert_fn: typing.Optional[typing.Callable[[Observable.Observable, typing.Optional[ItemPropertySlugType]], typing.Optional[str]]],
                 slug: str,
                 default_value: typing.Optional[str] = None) -> None:
        super().__init__(slug, default_value)
        self.__property = property
        self.__convert_fn = convert_fn
        self.__item_value_stream = Stream.PropertyChangedEventStream[ItemPropertySlugType](self._item_stream, self.__property)
        self.__item_value_stream_listener = self.__item_value_stream.value_stream.listen(weak_partial(ItemPropertySlug.__item_property_stream_value_changed, self))
        self.__item_property_stream_value_changed(self.__item_value_stream.value)

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> DynamicStringSlug:
        return ItemPropertySlug(self.__property, self.__convert_fn, self.slug_id, self.value)

    def __item_property_stream_value_changed(self, value: typing.Optional[ItemPropertySlugType]) -> None:
        def convert_to_str(value: typing.Optional[ItemPropertySlugType]) -> typing.Optional[str]:
            return str(value) if value is not None else None

        if self.__convert_fn:
            item = self._item_stream.value
            if item:
                self.value = self.__convert_fn(item, value)
            else:
                self.value = None
        else:
            self.value = convert_to_str(value)


class DynamicStringSlugString(DynamicString):
    """A dynamic string, comprised of dynamic string slugs, which produces a stream of rendered strings.

    Clients can observe the rendered_string_stream to get the rendered string.
    """

    def __init__(self, dynamic_string_type: str, dynamic_string_slugs: typing.Optional[typing.Sequence[DynamicStringSlug]] = None) -> None:
        super().__init__()
        self.__dynamic_string_type = dynamic_string_type
        self.__dynamic_string_slugs = list(dynamic_string_slugs) if dynamic_string_slugs else list()

        def combine(*vs: typing.Optional[str]) -> str:
            rendered_title = ' '.join([v or str() for v in vs])
            return ' '.join(rendered_title.strip().split())

        self.__stream = Stream.CombineLatestStream(self.__dynamic_string_slugs, combine)
        self.__stream_listener = self.__stream.value_stream.listen(weak_partial(DynamicStringSlugString.__handle_value_changed, self))
        self.__suppress_stream_listener = False
        self.__item: typing.Optional[Observable.Observable] = None

        self.__handle_value_changed(self.__stream.value)

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> DynamicString:
        dynamic_string_copy = DynamicStringSlugString(self.__dynamic_string_type)
        dynamic_string_copy.__copy_from(self)
        return dynamic_string_copy

    def __copy_from(self, dynamic_string: DynamicStringSlugString) -> None:
        self.__suppress_stream_listener = True
        try:
            while self.__stream.stream_list:
                self.__stream.remove_stream(0)
                self.__dynamic_string_slugs.pop(0)
            for dynamic_string_slug in dynamic_string.__dynamic_string_slugs:
                dynamic_string_slug_copy = copy.deepcopy(dynamic_string_slug)
                dynamic_string_slug_copy.set_item(self.__item)
                self.__stream.append_stream(dynamic_string_slug_copy)
                self.__dynamic_string_slugs.append(dynamic_string_slug_copy)
        finally:
            self.__suppress_stream_listener = False
        self.__handle_value_changed(self.__stream.value)

    # called by the owner of the dynamic string to connect the slugs to the observed item.
    def connect_item(self, item: typing.Optional[Observable.Observable]) -> None:
        self.__item = item
        for dynamic_string_slug in self.__dynamic_string_slugs:
            dynamic_string_slug.set_item(item)

    @property
    def _dynamic_string_slugs(self) -> typing.Sequence[DynamicStringSlug]:
        return self.__dynamic_string_slugs

    @property
    def _stream(self) -> Stream.AbstractStream[str]:
        return self.__stream

    def __handle_value_changed(self, value: typing.Optional[str]) -> None:
        if not self.__suppress_stream_listener:
            self.string_stream.value = value or str()
            self.persistence_stream.value = {
                "type": self.__dynamic_string_type,
                "slugs": [dynamic_string_slug.write_to_dict() for dynamic_string_slug in self.__dynamic_string_slugs]
            }


# for testing
class _TestDynamicString(DynamicString):
    value = "green"

    def __init__(self) -> None:
        super().__init__()
        self.string_stream.value = _TestDynamicString.value
        self.persistence_stream.value = {"type": "_test"}

    def read_from_dict(self, d: Persistence.PersistentDictType) -> None:
        self.string_stream.value = _TestDynamicString.value

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> DynamicString:
        return _TestDynamicString()


# for testing
_blocked_dynamic_string_factory: typing.Optional[str] = None


# construct a dynamic string from a dictionary. used internally only for now.
def make_dynamic_string(d: typing.Optional[Persistence.PersistentDictType]) -> typing.Optional[DynamicString]:
    if d:
        for component in Registry.get_components_by_type("dynamic-string-factory"):
            dynamic_string_type = d.get("type", None)
            if dynamic_string_type and dynamic_string_type != _blocked_dynamic_string_factory:
                if dynamic_string := typing.cast(DynamicStringFactory, component).make_dynamic_string(dynamic_string_type, d):
                    return dynamic_string
    return None


class DynamicStringFactory(typing.Protocol):
    """A protocol for factory for making a dynamic string from a template identifier."""
    def make_dynamic_string(self, dynamic_string_type: str, d: Persistence.PersistentDictType) -> typing.Optional[DynamicString]: ...


# used for testing
class _TestDynamicStringFactory(DynamicStringFactory):
    def make_dynamic_string(self, dynamic_string_type: str, d: Persistence.PersistentDictType) -> typing.Optional[DynamicString]:
        if dynamic_string_type == "_test":
            dynamic_string = _TestDynamicString()
            dynamic_string.read_from_dict(d)
            return dynamic_string
        if dynamic_string_type == "_slug_test":

            def convert_metadata_to_slug_test_str(item: Observable.Observable, value: typing.Optional[Persistence.PersistentDictType]) -> typing.Optional[str]:
                if value is not None:
                    metadata = value
                    return typing.cast(typing.Optional[str], metadata.get("_slug_test", None))
                else:
                    return None

            return DynamicStringSlugString(dynamic_string_type, [ItemPropertySlug("metadata", convert_metadata_to_slug_test_str, "slug_test")])
        return None


# register the factories.
Registry.register_component(_TestDynamicStringFactory(), {"dynamic-string-factory"})
