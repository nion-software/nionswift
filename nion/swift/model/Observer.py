from __future__ import annotations

# standard libraries
import abc
import collections
import copy
import functools
import itertools
import operator
import typing

# third party libraries
# None

# local libraries
from nion.utils import Event
from nion.utils import ListModel
from nion.utils import Observable


ItemValue = typing.Any


class AbstractItemSource(abc.ABC):

    @property
    @abc.abstractmethod
    def item_changed_event(self) -> Event.Event: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @property
    @abc.abstractmethod
    def item(self) -> ItemValue: ...


class AbstractItemSequenceSource(abc.ABC):

    @property
    @abc.abstractmethod
    def item_inserted_event(self) -> Event.Event: ...

    @property
    @abc.abstractmethod
    def item_removed_event(self) -> Event.Event: ...

    @property
    @abc.abstractmethod
    def item_mutated_event(self) -> Event.Event: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @property
    @abc.abstractmethod
    def items(self) -> typing.Sequence[ItemValue]: ...


class ItemSource(AbstractItemSource):
    """Provide a hard coded item source."""

    def __init__(self, item: ItemValue = None) -> None:
        self.__item = item
        self.__item_changed_event = Event.Event()

    def close(self) -> None:
        self.__item = None

    @property
    def item_changed_event(self) -> Event.Event:
        return self.__item_changed_event

    @property
    def item(self) -> ItemValue:
        return self.__item

    @item.setter
    def item(self, item: ItemValue) -> None:
        self.__item = item
        self.__item_changed_event.fire(item)


class PropertyItemSource(AbstractItemSource):
    """Provide an item source from a property of the item."""

    def __init__(self, item_source: AbstractItemSource, property: str) -> None:
        self.__item_source = item_source
        self.__property = property
        self.__last_value: ItemValue = None
        self.__item_changed_event = Event.Event()
        self.__item_source_changed_listener: typing.Optional[Event.EventListener] = None
        self.__property_changed_listener: typing.Optional[Event.EventListener] = None

        def send_value(value: typing.Optional[ItemValue]) -> None:
            if value != self.__last_value:
                self.__last_value = value
                self.__item_changed_event.fire(value)

        def item_changed(source: Observable.Observable) -> None:
            self.__unlisten()
            if source:
                def property_changed(property: str) -> None:
                    if property == self.__property:
                        send_value(getattr(source, self.__property, None))

                self.__property_changed_listener = source.property_changed_event.listen(property_changed)
                send_value(getattr(source, self.__property, None))
            else:
                send_value(None)

        self.__item_source_changed_listener = self.__item_source.item_changed_event.listen(item_changed)

        item_changed(self.__item_source.item)

    def close(self) -> None:
        self.__unlisten()
        if self.__item_source_changed_listener:
            self.__item_source_changed_listener.close()
            self.__item_source_changed_listener = None
        self.__item_source.close()
        self.__item_source = typing.cast(typing.Any, None)

    def __unlisten(self) -> None:
        if self.__property_changed_listener:
            self.__property_changed_listener.close()
            self.__property_changed_listener = None

    @property
    def item_changed_event(self) -> Event.Event:
        return self.__item_changed_event

    @property
    def item(self) -> ItemValue:
        return self.__last_value


class ArrayItemSource(AbstractItemSource):
    """Provide an item source from an array of the item."""

    def __init__(self, item_source: AbstractItemSource, property: str):
        self.__item_source = item_source
        self.__values: typing.List[ItemValue] = list()
        self.__item_changed_event = Event.Event()
        self.__item_inserted_listener: typing.Optional[Event.EventListener] = None
        self.__item_removed_listener: typing.Optional[Event.EventListener] = None

        def item_changed(source: Observable.Observable) -> None:
            self.__unlisten()
            if source:
                def item_inserted(key: str, value: ItemValue, index: int) -> None:
                    if key == property:
                        self.__values.insert(index, value)
                        self.__item_changed_event.fire(self.item)

                def item_removed(key: str, value: ItemValue, index: int) -> None:
                    if key == property:
                        self.__values.pop(index)
                        self.__item_changed_event.fire(self.item)

                self.__item_inserted_listener = source.item_inserted_event.listen(item_inserted)
                self.__item_removed_listener = source.item_removed_event.listen(item_removed)

                for index, value in enumerate(getattr(source, property)):
                    item_inserted(property, value, index)

            self.__item_changed_event.fire(self.item)

        self.__item_source_changed_listener = self.__item_source.item_changed_event.listen(item_changed)

        item_changed(self.__item_source.item)

    def close(self) -> None:
        self.__unlisten()
        self.__item_source_changed_listener.close()
        self.__item_source_changed_listener = typing.cast(typing.Any, None)
        self.__item_source.close()
        self.__item_source = typing.cast(typing.Any, None)

    def __unlisten(self) -> None:
        if self.__item_inserted_listener:
            self.__item_inserted_listener.close()
            self.__item_inserted_listener = None
        if self.__item_removed_listener:
            self.__item_removed_listener.close()
            self.__item_removed_listener = None

    @property
    def item_changed_event(self) -> Event.Event:
        return self.__item_changed_event

    @property
    def item(self) -> ItemValue:
        return copy.copy(self.__values)


AdapterInsertedFn = typing.Callable[[typing.Any, int], None]
AdapterRemovedFn = typing.Callable[[typing.Any, int], None]

class AbstractArraySourceAdapter(abc.ABC):

    @abc.abstractmethod
    def close(self) -> None: ...

    @property
    @abc.abstractmethod
    def items(self) -> typing.Sequence[ItemValue]: ...


AdapterFactory = typing.Callable[[typing.Any, AdapterInsertedFn, AdapterRemovedFn], AbstractArraySourceAdapter]


class ArrayArraySourceAdapter(AbstractArraySourceAdapter):

    @classmethod
    def factory(cls, key: str, *, predicate: typing.Optional[typing.Callable[[ItemValue], bool]] = None,
                mapping: typing.Optional[typing.Callable[[ItemValue], ItemValue]] = None) -> AdapterFactory:
        def make_adapter(s: Observable.Observable, insert: AdapterInsertedFn, remove: AdapterRemovedFn) -> AbstractArraySourceAdapter:
            return ArrayArraySourceAdapter(s, insert, remove, key, predicate=predicate, mapping=mapping)
        return make_adapter

    def __init__(self, source: Observable.Observable, inserted: AdapterInsertedFn, removed: AdapterRemovedFn, key: str,
                 *, predicate: typing.Optional[typing.Callable[[ItemValue], bool]] = None,
                 mapping: typing.Optional[typing.Callable[[ItemValue], ItemValue]] = None) -> None:
        self.__key = key
        self.__predicate = predicate or (lambda x: bool(x))
        self.__mapping = mapping or (lambda x: x)
        self.__items: typing.OrderedDict[ItemValue, ItemValue] = collections.OrderedDict()

        def item_inserted(key: str, item: ItemValue, index: int) -> None:
            if key == self.__key and self.__predicate(item):
                mapped_item = self.__mapping(item) if item else None
                index = len(self.__items)
                self.__items[item] = mapped_item
                inserted(mapped_item, index)

        def item_removed(key: str, item: ItemValue, index: int) -> None:
            if key == self.__key and item in self.__items:
                index = list(self.__items.keys()).index(item)
                mapped_item = self.__items.pop(item)
                removed(mapped_item, index)

        self.__item_inserted_listener = source.item_inserted_event.listen(item_inserted)
        self.__item_removed_listener = source.item_removed_event.listen(item_removed)
        for index, item in enumerate(getattr(source, self.__key)):
            item_inserted(self.__key, item, index)

    def close(self) -> None:
        self.__item_inserted_listener.close()
        self.__item_inserted_listener = typing.cast(typing.Any, None)
        self.__item_removed_listener.close()
        self.__item_removed_listener = typing.cast(typing.Any, None)

    @property
    def items(self) -> typing.Sequence[ItemValue]:
        return list(self.__items.values())


class OrderedArrayArraySourceAdapter(AbstractArraySourceAdapter):

    @classmethod
    def factory(cls, key: str, *, predicate: typing.Optional[typing.Callable[[ItemValue], bool]] = None) -> AdapterFactory:
        def make_adapter(s: Observable.Observable, insert: AdapterInsertedFn, remove: AdapterRemovedFn) -> AbstractArraySourceAdapter:
            return OrderedArrayArraySourceAdapter(s, insert, remove, key, predicate=predicate)
        return make_adapter

    def __init__(self, source: Observable.Observable, inserted: AdapterInsertedFn, removed: AdapterRemovedFn, key: str,
                 *, predicate: typing.Optional[typing.Callable[[ItemValue], bool]] = None):
        self.__list_model = ListModel.FilteredListModel(container=source, items_key=key)
        self.__items: typing.List[ItemValue] = list()

        if predicate:
            self.__list_model.filter = ListModel.PredicateFilter(predicate)

        def item_inserted(key: str, item: ItemValue, index: int) -> None:
            self.__items.insert(index, item)
            inserted(item, index)

        def item_removed(key: str, item: ItemValue, index: int) -> None:
            self.__items.pop(index)
            removed(item, index)

        self.__item_inserted_listener = self.__list_model.item_inserted_event.listen(item_inserted)
        self.__item_removed_listener = self.__list_model.item_removed_event.listen(item_removed)

        for index, item in enumerate(self.__list_model.items):
            item_inserted(key, item, index)

    def close(self) -> None:
        self.__item_inserted_listener.close()
        self.__item_inserted_listener = typing.cast(typing.Any, None)
        self.__item_removed_listener.close()
        self.__item_removed_listener = typing.cast(typing.Any, None)
        self.__list_model.close()
        self.__list_model = typing.cast(typing.Any, None)
        self.__items = typing.cast(typing.Any, None)

    @property
    def items(self) -> typing.Sequence[ItemValue]:
        return copy.copy(self.__items)


class SetArraySourceAdapter(AbstractArraySourceAdapter):

    @classmethod
    def factory(cls, key: str, *, predicate: typing.Optional[typing.Callable[[ItemValue], bool]] = None,
                mapping: typing.Optional[typing.Callable[[ItemValue], ItemValue]] = None) -> AdapterFactory:
        def make_adapter(s: Observable.Observable, insert: AdapterInsertedFn, remove: AdapterRemovedFn) -> AbstractArraySourceAdapter:
            return SetArraySourceAdapter(s, insert, remove, key, predicate=predicate, mapping=mapping)
        return make_adapter

    def __init__(self, source: Observable.Observable, inserted: AdapterInsertedFn, removed: AdapterRemovedFn, key: str,
                 *, predicate: typing.Optional[typing.Callable[[ItemValue], bool]] = None,
                 mapping: typing.Optional[typing.Callable[[ItemValue], ItemValue]] = None) -> None:
        self.__key = key
        self.__predicate = predicate or (lambda x: bool(x))
        self.__mapping = mapping or (lambda x: x)
        self.__items: typing.OrderedDict[ItemValue, ItemValue] = collections.OrderedDict()

        def item_added(key: str, item: ItemValue) -> None:
            if key == self.__key and self.__predicate(item):
                mapped_item = self.__mapping(item) if item else None
                index = len(self.__items)
                self.__items[item] = mapped_item
                inserted(mapped_item, index)

        def item_discarded(key: str, item: ItemValue) -> None:
            if key == self.__key and item in self.__items:
                index = list(self.__items.keys()).index(item)
                mapped_item = self.__items.pop(item)
                removed(mapped_item, index)

        self.__item_added_listener = source.item_added_event.listen(item_added)
        self.__item_discarded_listener = source.item_discarded_event.listen(item_discarded)
        for item in getattr(source, self.__key):
            item_added(self.__key, item)

    def close(self) -> None:
        self.__item_added_listener.close()
        self.__item_added_listener = typing.cast(typing.Any, None)
        self.__item_discarded_listener.close()
        self.__item_discarded_listener = typing.cast(typing.Any, None)
        self.__items = typing.cast(typing.Any, None)

    @property
    def items(self) -> typing.Sequence[ItemValue]:
        return list(self.__items.values())


class ItemSequenceSource(AbstractItemSequenceSource):

    def __init__(self, item_source: AbstractItemSource, adapter_factory: AdapterFactory) -> None:
        self.__item_source = item_source
        self.__source: typing.Optional[Observable.Observable] = None
        self.__item_inserted_event = Event.Event()
        self.__item_removed_event = Event.Event()
        self.__item_mutated_event = Event.Event()
        self.__adapter : typing.Optional[AbstractArraySourceAdapter] = None

        def item_changed(source: Observable.Observable) -> None:
            if self.__adapter:
                self.__adapter.close()
                self.__adapter = None
            if source:
                inserted = typing.cast(AdapterInsertedFn, self.__item_inserted_event.fire)
                removed = typing.cast(AdapterRemovedFn, self.__item_removed_event.fire)
                self.__adapter = adapter_factory(source, inserted, removed)

        self.__item_source_changed_listener = self.__item_source.item_changed_event.listen(item_changed)

        item_changed(self.__item_source.item)

    def close(self) -> None:
        self.__item_source_changed_listener.close()
        self.__item_source_changed_listener = typing.cast(typing.Any, None)
        self.__item_source.close()
        self.__item_source = typing.cast(typing.Any, None)
        if self.__adapter:
            self.__adapter.close()
            self.__adapter = None

    @property
    def item_inserted_event(self) -> Event.Event:
        return self.__item_inserted_event

    @property
    def item_removed_event(self) -> Event.Event:
        return self.__item_removed_event

    @property
    def item_mutated_event(self) -> Event.Event:
        return self.__item_mutated_event

    @property
    def items(self) -> typing.Sequence[ItemValue]:
        return self.__adapter.items if self.__adapter else list()


class AbstractItemTransformer(abc.ABC):

    @abc.abstractmethod
    def close(self) -> None: ...

    @property
    @abc.abstractmethod
    def item(self) -> ItemValue: ...


TransfomerMutatedFn = typing.Callable[[AbstractItemTransformer], None]
TransformerFactory = typing.Callable[[ItemValue, TransfomerMutatedFn], AbstractItemTransformer]


class PropertyItemTransformer(AbstractItemTransformer):

    @classmethod
    def factory(cls, property: str) -> TransformerFactory:
        # mutate is a callback to the transformer
        def make_transformer(item: ItemValue, mutate: TransfomerMutatedFn) -> AbstractItemTransformer:
            return cls(item, mutate, property)
        return make_transformer

    def __init__(self, item: ItemValue, mutate: TransfomerMutatedFn, property: str) -> None:
        self.__constructed_item = PropertyItemSource(ItemSource(item), property)

        def item_changed(source: Observable.Observable) -> None:
            mutate(self)

        self.__item_changed_listener = self.__constructed_item.item_changed_event.listen(item_changed)

    def close(self) -> None:
        self.__item_changed_listener.close()
        self.__item_changed_listener = typing.cast(typing.Any, None)
        self.__constructed_item.close()
        self.__constructed_item = typing.cast(typing.Any, None)

    @property
    def item(self) -> ItemValue:
        return self.__constructed_item.item


class ArrayItemTransformer(AbstractItemTransformer):

    @classmethod
    def factory(cls, property: str) -> TransformerFactory:
        # mutate is a callback to the transformer
        def make_transformer(item: ItemValue, mutate: TransfomerMutatedFn) -> AbstractItemTransformer:
            return cls(item, mutate, property)
        return make_transformer

    def __init__(self, item: ItemValue, mutate: TransfomerMutatedFn, property: str) -> None:
        self.__constructed_item = ArrayItemSource(ItemSource(item), property)

        def item_changed(source: Observable.Observable) -> None:
            mutate(self)

        self.__item_changed_listener = self.__constructed_item.item_changed_event.listen(item_changed)

    def close(self) -> None:
        self.__item_changed_listener.close()
        self.__item_changed_listener = typing.cast(typing.Any, None)
        self.__constructed_item.close()
        self.__constructed_item = typing.cast(typing.Any, None)

    @property
    def item(self) -> ItemValue:
        return self.__constructed_item.item


class FunctionItemTransformer(AbstractItemTransformer):

    @classmethod
    def factory(cls, fn: typing.Callable[[ItemValue], ItemValue]) -> TransformerFactory:
        # mutate is a callback to the transformer
        def make_transformer(item: ItemValue, mutate: TransfomerMutatedFn) -> AbstractItemTransformer:
            return cls(item, mutate, fn)
        return make_transformer

    def __init__(self, item: ItemValue, mutate: TransfomerMutatedFn, fn: typing.Callable[[ItemValue], ItemValue]):
        self.__value = fn(item)

    def close(self) -> None:
        self.__value = None

    @property
    def item(self) -> ItemValue:
        return self.__value


class TransformedItemSource(AbstractItemSource):

    def __init__(self, item_source: AbstractItemSource, transformer_factory: TransformerFactory) -> None:
        self.__item_source = item_source
        self.__item_changed_event = Event.Event()
        self.__item_value = None
        self.__transformer = None

        def transformer_item_changed(transformer: AbstractItemTransformer) -> None:
            self.__item_changed_event.fire(transformer.item)

        def item_changed(source: Observable.Observable) -> None:
            if self.__transformer:
                self.__transformer.close()
            self.__transformer = transformer_factory(self.__item_source.item, transformer_item_changed)
            self.__item_changed_event.fire(self.__transformer.item)

        self.__item_source_changed_listener = self.__item_source.item_changed_event.listen(item_changed)

        item_changed(self.__item_source.item)

    def close(self) -> None:
        if self.__transformer:
            self.__transformer.close()
            self.__transformer = None
        self.__item_source_changed_listener.close()
        self.__item_source_changed_listener = typing.cast(typing.Any, None)
        self.__item_source.close()
        self.__item_source = typing.cast(typing.Any, None)
        self.__item_value = None

    @property
    def item_changed_event(self) -> Event.Event:
        return self.__item_changed_event

    @property
    def item(self) -> ItemValue:
        return self.__transformer.item if self.__transformer else None


class TransformedItemSequence(AbstractItemSequenceSource):

    def __init__(self, item_sequence_source: AbstractItemSequenceSource, transformer_factory: TransformerFactory) -> None:
        self.__item_sequence_source = item_sequence_source
        self.__item_inserted_event = Event.Event()
        self.__item_removed_event = Event.Event()
        self.__item_mutated_event = Event.Event()
        self.__transformers: typing.List[AbstractItemTransformer] = list()

        def item_changed(transformer: AbstractItemTransformer) -> None:
            index = self.__transformers.index(transformer)
            self.__item_mutated_event.fire(transformer.item, index)

        def item_inserted(item: ItemValue, index: int) -> None:
            transformer = transformer_factory(item, item_changed)
            self.__transformers.insert(index, transformer)
            self.__item_inserted_event.fire(transformer.item, index)

        def item_removed(item: ItemValue, index: int) -> None:
            constructed_item = self.__transformers.pop(index)
            self.__item_removed_event.fire(constructed_item.item, index)
            constructed_item.close()

        def item_mutated(item: ItemValue, index: int) -> None:
            self.__transformers[index].close()
            transformer = transformer_factory(item, item_changed)
            self.__transformers[index] = transformer
            self.__item_mutated_event.fire(transformer.item, index)

        self.__item_inserted_listener = self.__item_sequence_source.item_inserted_event.listen(item_inserted)
        self.__item_removed_listener = self.__item_sequence_source.item_removed_event.listen(item_removed)
        self.__item_mutated_listener = self.__item_sequence_source.item_mutated_event.listen(item_mutated)

        for index, item in enumerate(self.__item_sequence_source.items):
            item_inserted(item, index)

    def close(self) -> None:
        self.__item_inserted_listener.close()
        self.__item_inserted_listener = typing.cast(typing.Any, None)
        self.__item_removed_listener.close()
        self.__item_removed_listener = typing.cast(typing.Any, None)
        self.__item_mutated_listener.close()
        self.__item_mutated_listener = typing.cast(typing.Any, None)
        for item in self.__transformers:
            item.close()
        self.__transformers = typing.cast(typing.Any, None)
        self.__item_sequence_source.close()
        self.__item_sequence_source = typing.cast(typing.Any, None)

    @property
    def item_inserted_event(self) -> Event.Event:
        return self.__item_inserted_event

    @property
    def item_removed_event(self) -> Event.Event:
        return self.__item_removed_event

    @property
    def item_mutated_event(self) -> Event.Event:
        return self.__item_mutated_event

    @property
    def items(self) -> typing.Sequence[ItemValue]:
        return [item.item for item in self.__transformers]


class FilteredItemSequence(AbstractItemSequenceSource):

    def __init__(self, item_sequence_source: AbstractItemSequenceSource, predicate: typing.Callable[[ItemValue], bool]) -> None:
        self.__item_sequence_source = item_sequence_source
        self.__list_model = ListModel.ListModel[ItemValue](key="items")
        self.__filtered_list_model = ListModel.FilteredListModel(container=self.__list_model, items_key="items")
        self.__filtered_list_model.filter = ListModel.PredicateFilter(lambda x: predicate(x.value))
        self.__item_inserted_event = Event.Event()
        self.__item_removed_event = Event.Event()
        self.__item_mutated_event = Event.Event()

        class Wrapper:  # used to wrap values so that they are all unique
            def __init__(self, value: ItemValue) -> None: self.value = value

        def item_inserted(item: ItemValue, index: int) -> None:
            self.__list_model.insert_item(index, Wrapper(item))

        def item_removed(item: ItemValue, index: int) -> None:
            self.__list_model.remove_item(index)

        def item_mutated(item: ItemValue, index: int) -> None:
            self.__list_model.remove_item(index)
            self.__list_model.insert_item(index, Wrapper(item))

        self.__item_inserted_listener = self.__item_sequence_source.item_inserted_event.listen(item_inserted)
        self.__item_removed_listener = self.__item_sequence_source.item_removed_event.listen(item_removed)
        self.__item_mutated_listener = self.__item_sequence_source.item_mutated_event.listen(item_mutated)

        def filtered_item_inserted(key: str, item: ItemValue, index: int) -> None:
            self.__item_inserted_event.fire(typing.cast(Wrapper, item).value, index)

        def filtered_item_removed(key: str, item: ItemValue, index: int) -> None:
            self.__item_removed_event.fire(typing.cast(Wrapper, item).value, index)

        self.__filtered_item_inserted_listener = self.__filtered_list_model.item_inserted_event.listen(filtered_item_inserted)
        self.__filtered_item_removed_listener = self.__filtered_list_model.item_removed_event.listen(filtered_item_removed)

        for index, item in enumerate(self.__item_sequence_source.items):
            item_inserted(item, index)

    def close(self) -> None:
        self.__item_inserted_listener.close()
        self.__item_inserted_listener = typing.cast(typing.Any, None)
        self.__item_removed_listener.close()
        self.__item_removed_listener = typing.cast(typing.Any, None)
        self.__item_mutated_listener.close()
        self.__item_mutated_listener = typing.cast(typing.Any, None)
        self.__filtered_item_inserted_listener.close()
        self.__filtered_item_inserted_listener = typing.cast(typing.Any, None)
        self.__filtered_item_removed_listener.close()
        self.__filtered_item_removed_listener = typing.cast(typing.Any, None)
        self.__filtered_list_model.close()
        self.__filtered_list_model = typing.cast(typing.Any, None)
        self.__list_model.close()
        self.__list_model = typing.cast(typing.Any, None)
        self.__item_sequence_source.close()
        self.__item_sequence_source = typing.cast(typing.Any, None)

    @property
    def item_inserted_event(self) -> Event.Event:
        return self.__item_inserted_event

    @property
    def item_removed_event(self) -> Event.Event:
        return self.__item_removed_event

    @property
    def item_mutated_event(self) -> Event.Event:
        return self.__item_mutated_event

    @property
    def items(self) -> typing.Sequence[ItemValue]:
        return [item.value for item in self.__filtered_list_model.items]


class MappedItemSequence(AbstractItemSequenceSource):

    def __init__(self, item_sequence_source: AbstractItemSequenceSource, map_fn: typing.Callable[[typing.Optional[AbstractItemSource]], typing.Optional[AbstractItemSource]]):
        self.__item_sequence_source = item_sequence_source
        self.__item_inserted_event = Event.Event()
        self.__item_removed_event = Event.Event()
        self.__item_mutated_event = Event.Event()
        self.__mapped_items: typing.List[AbstractItemSource] = list()
        self.__mapped_item_listeners: typing.List[Event.EventListener] = list()

        def item_changed(mapped_item: AbstractItemSource, item: ItemValue) -> None:
            index = self.__mapped_items.index(mapped_item)
            self.__item_mutated_event.fire(mapped_item.item, index)

        def item_inserted(item: ItemValue, index: int) -> None:
            mapped_item = map_fn(ItemSource(item))
            assert mapped_item is not None
            self.__mapped_items.insert(index, mapped_item)
            self.__mapped_item_listeners.insert(index, mapped_item.item_changed_event.listen(functools.partial(item_changed, mapped_item)))
            self.__item_inserted_event.fire(mapped_item.item, index)

        def item_removed(item: ItemValue, index: int) -> None:
            self.__mapped_item_listeners.pop(index).close()
            mapped_item = self.__mapped_items.pop(index)
            self.__item_removed_event.fire(mapped_item.item, index)
            mapped_item.close()

        def item_mutated(item: ItemValue, index: int) -> None:
            self.__mapped_item_listeners[index].close()
            self.__mapped_items[index].close()
            mapped_item = map_fn(ItemSource(item))
            assert mapped_item is not None
            self.__mapped_items[index] = mapped_item
            self.__mapped_item_listeners[index] = mapped_item.item_changed_event.listen(functools.partial(item_changed, mapped_item))
            self.__item_mutated_event.fire(mapped_item.item, index)

        self.__item_inserted_listener = self.__item_sequence_source.item_inserted_event.listen(item_inserted)
        self.__item_removed_listener = self.__item_sequence_source.item_removed_event.listen(item_removed)
        self.__item_mutated_listener = self.__item_sequence_source.item_mutated_event.listen(item_mutated)

        for index, item in enumerate(self.__item_sequence_source.items):
            item_inserted(item, index)

    def close(self) -> None:
        self.__item_inserted_listener.close()
        self.__item_inserted_listener = typing.cast(typing.Any, None)
        self.__item_removed_listener.close()
        self.__item_removed_listener = typing.cast(typing.Any, None)
        self.__item_mutated_listener.close()
        self.__item_mutated_listener = typing.cast(typing.Any, None)
        for mapped_item_listener in self.__mapped_item_listeners:
            mapped_item_listener.close()
        self.__mapped_item_listeners = typing.cast(typing.Any, None)
        for item in self.__mapped_items:
            item.close()
        self.__mapped_items = typing.cast(typing.Any, None)
        self.__item_sequence_source.close()
        self.__item_sequence_source = typing.cast(typing.Any, None)

    @property
    def item_inserted_event(self) -> Event.Event:
        return self.__item_inserted_event

    @property
    def item_removed_event(self) -> Event.Event:
        return self.__item_removed_event

    @property
    def item_mutated_event(self) -> Event.Event:
        return self.__item_mutated_event

    @property
    def items(self) -> typing.Sequence[ItemValue]:
        return [item.item for item in self.__mapped_items]


class AbstractAction(abc.ABC):

    @abc.abstractmethod
    def close(self) -> None: ...


class ItemSequenceAction:
    """Monitor an item set source and create an action on each item."""

    def __init__(self, item_sequence_source: AbstractItemSequenceSource, action: typing.Callable[[AbstractItemSource], AbstractAction]):
        self.__item_sequence_source = item_sequence_source
        self.__item_actions: typing.Dict[ItemValue, AbstractAction] = dict()

        def item_inserted(item: ItemValue, index: int) -> None:
            self.__item_actions[item] = action(ItemSource(item))

        def item_removed(item: ItemValue, index: int) -> None:
            self.__item_actions.pop(item).close()

        def item_mutated(item: ItemValue, index: int) -> None:
            self.__item_actions[item].close()
            self.__item_actions[item] = action(ItemSource(item))

        self.__item_inserted_listener = self.__item_sequence_source.item_inserted_event.listen(item_inserted)
        self.__item_removed_listener = self.__item_sequence_source.item_removed_event.listen(item_removed)
        self.__item_mutated_listener = self.__item_sequence_source.item_mutated_event.listen(item_mutated)

        for index, item in enumerate(self.__item_sequence_source.items):
            item_inserted(item, index)

    def close(self) -> None:
        self.__item_inserted_listener.close()
        self.__item_inserted_listener = typing.cast(typing.Any, None)
        self.__item_removed_listener.close()
        self.__item_removed_listener = typing.cast(typing.Any, None)
        self.__item_mutated_listener.close()
        self.__item_mutated_listener = typing.cast(typing.Any, None)
        for item, item_action in self.__item_actions.items():
            item_action.close()
        self.__item_actions = typing.cast(typing.Any, None)
        self.__item_sequence_source.close()
        self.__item_sequence_source = typing.cast(typing.Any, None)


class ItemSequenceTrampoline:
    """Monitor an item set source and send the action to another object."""

    def __init__(self, item_sequence_source: AbstractItemSequenceSource, target: Observable.Observable, key: str) -> None:
        self.__item_sequence_source = item_sequence_source
        self.__items: typing.List[ItemValue] = list()

        def item_inserted(item: ItemValue, index: int) -> None:
            self.__items.insert(index, item)
            target.notify_insert_item(key, item, index)

        def item_removed(item: ItemValue, index: int) -> None:
            self.__items.pop(index)
            target.notify_remove_item(key, item, index)

        self.__item_inserted_listener = self.__item_sequence_source.item_inserted_event.listen(item_inserted)
        self.__item_removed_listener = self.__item_sequence_source.item_removed_event.listen(item_removed)

        for index, item in enumerate(self.__item_sequence_source.items):
            item_inserted(item, index)

    def close(self) -> None:
        self.__item_inserted_listener.close()
        self.__item_inserted_listener = typing.cast(typing.Any, None)
        self.__item_removed_listener.close()
        self.__item_removed_listener = typing.cast(typing.Any, None)
        self.__items = typing.cast(typing.Any, None)
        self.__item_sequence_source.close()
        self.__item_sequence_source = typing.cast(typing.Any, None)

    @property
    def item(self) -> ItemValue:
        return self.__items


class AbstractItemSequenceReducer(abc.ABC):

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def item_inserted(self, item: ItemValue, index: int) -> bool: ...

    @abc.abstractmethod
    def item_removed(self, item: ItemValue, index: int) -> bool: ...

    @abc.abstractmethod
    def item_mutated(self, item: ItemValue, index: int) -> bool: ...

    @property
    @abc.abstractmethod
    def item(self) -> ItemValue: ...


class ItemSequenceCollector(AbstractItemSequenceReducer):

    def __init__(self) -> None:
        self.__items: typing.List[ItemValue] = list()

    def close(self) -> None:
        self.__items = typing.cast(typing.Any, None)

    def item_inserted(self, item: ItemValue, index: int) -> bool:
        self.__items.insert(index, item)
        return True

    def item_removed(self, item: ItemValue, index: int) -> bool:
        self.__items.pop(index)
        return True

    def item_mutated(self, item: ItemValue, index: int) -> bool:
        self.__items[index] = item
        return True

    @property
    def item(self) -> ItemValue:
        return copy.copy(self.__items)


class ItemSequenceLength(AbstractItemSequenceReducer):

    def __init__(self) -> None:
        self.__items: typing.List[ItemValue] = list()

    def close(self) -> None:
        self.__items = typing.cast(typing.Any, None)

    def item_inserted(self, item: ItemValue, index: int) -> bool:
        self.__items.insert(index, item)
        return True

    def item_removed(self, item: ItemValue, index: int) -> bool:
        self.__items.pop(index)
        return True

    def item_mutated(self, item: ItemValue, index: int) -> bool:
        return False

    @property
    def item(self) -> ItemValue:
        return len(self.__items)


class ItemSequenceListReducer(AbstractItemSource):
    """Monitor an item set source and run a reducer on it to produce an item value."""

    def __init__(self, item_sequence_source: AbstractItemSequenceSource, reducer: AbstractItemSequenceReducer) -> None:
        self.__item_sequence_source = item_sequence_source
        self.__item_reducer = reducer
        self.__item_changed_event = Event.Event()

        def item_inserted(item: ItemValue, index: int) -> None:
            if self.__item_reducer.item_inserted(item, index):
                self.item_changed_event.fire(self.item)

        def item_removed(item: ItemValue, index: int) -> None:
            if self.__item_reducer.item_removed(item, index):
                self.item_changed_event.fire(self.item)

        def item_mutated(item: ItemValue, index: int) -> None:
            if self.__item_reducer.item_mutated(item, index):
                self.item_changed_event.fire(self.item)

        self.__item_inserted_listener = self.__item_sequence_source.item_inserted_event.listen(item_inserted)
        self.__item_removed_listener = self.__item_sequence_source.item_removed_event.listen(item_removed)
        self.__item_mutated_listener = self.__item_sequence_source.item_mutated_event.listen(item_mutated)

        for index, item in enumerate(self.__item_sequence_source.items):
            item_inserted(item, index)

    def close(self) -> None:
        self.__item_inserted_listener.close()
        self.__item_inserted_listener = typing.cast(typing.Any, None)
        self.__item_removed_listener.close()
        self.__item_removed_listener = typing.cast(typing.Any, None)
        self.__item_mutated_listener.close()
        self.__item_mutated_listener = typing.cast(typing.Any, None)
        self.__item_sequence_source.close()
        self.__item_sequence_source = typing.cast(typing.Any, None)
        self.__item_reducer.close()
        self.__item_reducer = typing.cast(typing.Any, None)

    @property
    def item_changed_event(self) -> Event.Event:
        return self.__item_changed_event

    @property
    def item(self) -> ItemValue:
        return self.__item_reducer.item


class ItemSequenceIndex(AbstractItemSource):

    def __init__(self, item_sequence_source: AbstractItemSequenceSource, index: int) -> None:
        self.__item_sequence_source = item_sequence_source
        self.__index = index
        self.__item: typing.Optional[ItemValue] = None
        self.__item_changed_event = Event.Event()

        def update_item() -> None:
            items = self.__item_sequence_source.items
            item = items[index] if len(items) > index else None
            if item != self.__item:
                self.__item = item
                self.item_changed_event.fire(self.__item)

        def item_inserted(item: ItemValue, index: int) -> None:
            update_item()

        def item_removed(item: ItemValue, index: int) -> None:
            update_item()

        def item_mutated(item: ItemValue, index: int) -> None:
            update_item()

        self.__item_inserted_listener = self.__item_sequence_source.item_inserted_event.listen(item_inserted)
        self.__item_removed_listener = self.__item_sequence_source.item_removed_event.listen(item_removed)
        self.__item_mutated_listener = self.__item_sequence_source.item_mutated_event.listen(item_mutated)

        update_item()

    def close(self) -> None:
        self.__item_inserted_listener.close()
        self.__item_inserted_listener = typing.cast(typing.Any, None)
        self.__item_removed_listener.close()
        self.__item_removed_listener = typing.cast(typing.Any, None)
        self.__item_mutated_listener.close()
        self.__item_mutated_listener = typing.cast(typing.Any, None)
        self.__item_sequence_source.close()
        self.__item_sequence_source = typing.cast(typing.Any, None)
        self.__item = None

    @property
    def item_changed_event(self) -> Event.Event:
        return self.__item_changed_event

    @property
    def item(self) -> ItemValue:
        return self.__item


class ItemTuple(AbstractItemSource):

    def __init__(self, *items: typing.Optional[AbstractItemSource]):
        self.__items = items
        self.__item_changed_listeners: typing.List[typing.Optional[Event.EventListener]] = list()
        self.__values: typing.List[ItemValue] = list()
        self.__item_changed_event = Event.Event()

        def item_changed(index: int, item: ItemValue) -> None:
            if item != self.__values[index]:
                self.__values[index] = item
                self.item_changed_event.fire(self.item)

        for index, item in enumerate(self.__items):
            item_changed_listener = item.item_changed_event.listen(functools.partial(item_changed, index)) if item else None
            self.__item_changed_listeners.append(item_changed_listener)
            self.__values.append(item.item if item else None)

    def close(self) -> None:
        for item_changed_listener in self.__item_changed_listeners:
            if item_changed_listener:
                item_changed_listener.close()
        self.__item_changed_listeners = typing.cast(typing.Any, None)
        for item in self.__items:
            if item:
                item.close()
        self.__items = typing.cast(typing.Any, None)
        self.__values = typing.cast(typing.Any, None)

    @property
    def item_changed_event(self) -> Event.Event:
        return self.__item_changed_event

    @property
    def item(self) -> ItemValue:
        return tuple(self.__values)


class ItemAction(AbstractAction):

    def __init__(self, item_source: AbstractItemSource, action_factory: typing.Callable[[AbstractItemSource], AbstractAction]):
        self.__item_source = item_source
        self.__item_action = None
        self.__item = None

        def item_changed(item: ItemValue) -> None:
            if item != self.__item:
                if self.__item_action:
                    self.__item_action.close()
                self.__item_action = action_factory(ItemSource(item)) if item else None

        self.__item_changed_listener = item_source.item_changed_event.listen(item_changed)

        item_changed(self.__item_source.item)

    def close(self) -> None:
        if self.__item_action:
            self.__item_action.close()
        self.__item_action = None
        self.__item = None
        self.__item_changed_listener.close()
        self.__item_changed_listener = typing.cast(typing.Any, None)
        self.__item_source.close()
        self.__item_source = typing.cast(typing.Any, None)


class ItemMonitor(AbstractAction):

    def __init__(self, item_source: AbstractItemSource, fn: typing.Callable[[ItemValue], None]) -> None:
        self.__item_source = item_source

        def item_changed(item: ItemValue) -> None:
            fn(item)

        self.__item_changed_listener = item_source.item_changed_event.listen(item_changed)

        item_changed(self.__item_source.item)

    def close(self) -> None:
        self.__item_changed_listener.close()
        self.__item_changed_listener = typing.cast(typing.Any, None)
        self.__item_source.close()
        self.__item_source = typing.cast(typing.Any, None)


class ObserverBuilder:
    """The observer builder base. Constructs an observable. Provides root item."""

    def __init__(self) -> None:
        self.__fns: typing.List[typing.Callable[[ItemValue], AbstractItemSource]] = list()

    def close(self) -> None:
        self.__fns = typing.cast(typing.Any, None)

    def make_observable(self) -> typing.Optional[AbstractItemSource]:
        """Returns an observable, which must be closed."""
        return self._apply(None)

    def _apply(self, node: typing.Optional[AbstractItemSource]) -> typing.Optional[AbstractItemSource]:
        o = node
        for fn in self.__fns:
            o = fn(o)
        return o

    def _build(self, fn: typing.Callable[[ItemValue], AbstractItemSource]) -> None:
        self.__fns.append(fn)

    def source(self, item_value: ItemValue) -> ObserverBuilderItemSource:
        """Build an observer source from the item_value."""
        self._build(lambda node: ItemSource(item_value))
        return ObserverBuilderItemSource(self)

    @property
    def x(self) -> ObserverBuilderItemSource:
        """Build an observer item source base, used as input to functions iterating over a collection."""
        return ObserverBuilderItemSource(ObserverBuilder())


class ObserverBuilderItemSource:
    """The observer builder for item sources."""

    def __init__(self, base: ObserverBuilder):
        self.__base = base

    def _build(self, fn: typing.Callable[[typing.Any], typing.Any]) -> None:
        self.__base._build(fn)

    @property
    def base(self) -> ObserverBuilder:
        return self.__base

    def sequence_from_array(self, key: str, *, predicate: typing.Optional[typing.Callable[[ItemValue], bool]] = None) -> ObserverBuilderItemSequenceSource:
        """Builds an unordered item sequence from the observable array specified by key and filtered by predicate."""
        self._build(lambda node: ItemSequenceSource(typing.cast(AbstractItemSource, node), ArrayArraySourceAdapter.factory(key, predicate=predicate)))
        return ObserverBuilderItemSequenceSource(self.base)

    def ordered_sequence_from_array(self, key: str, *, predicate: typing.Optional[typing.Callable[[ItemValue], bool]] = None) -> ObserverBuilderItemSequenceSource:
        """Builds an ordered item sequence from the observable array specified by key and filtered by predicate. Slower."""
        self._build(lambda node: ItemSequenceSource(typing.cast(AbstractItemSource, node), OrderedArrayArraySourceAdapter.factory(key, predicate=predicate)))
        return ObserverBuilderItemSequenceSource(self.base)

    def sequence_from_set(self, key: str, *, predicate: typing.Optional[typing.Callable[[ItemValue], bool]] = None) -> ObserverBuilderItemSequenceSource:
        """Builds an unordered item sequence from the observable set specified by key and filtered by predicate."""
        self._build(lambda node: ItemSequenceSource(typing.cast(AbstractItemSource, node), SetArraySourceAdapter.factory(key, predicate=predicate)))
        return ObserverBuilderItemSequenceSource(self.base)

    def print(self) -> ObserverBuilderItemAction:
        """Build an action to print the item."""
        self._build(lambda node: ItemMonitor(typing.cast(AbstractItemSource, node), print))
        return ObserverBuilderItemAction(self.base)

    def action(self, action: typing.Callable[[ItemValue], AbstractAction]) -> ObserverBuilderItemAction:
        """Build an action on the item."""
        def make_action(node: AbstractItemSource) -> AbstractAction:
            return action(node.item)
        self._build(lambda node: ItemAction(typing.cast(AbstractItemSource, node), make_action))
        return ObserverBuilderItemAction(self.base)

    def action_fn(self, item_changed: typing.Callable[[ItemValue], None]) -> ObserverBuilderItemAction:
        """Build an action on the item."""
        self._build(lambda node: ItemMonitor(typing.cast(AbstractItemSource, node), item_changed))
        return ObserverBuilderItemAction(self.base)

    def prop(self, property: str) -> ObserverBuilderItemSource:
        """Build a property observer on the item. The item will be the property."""
        self._build(lambda node: TransformedItemSource(typing.cast(AbstractItemSource, node), PropertyItemTransformer.factory(property)))
        return ObserverBuilderItemSource(self.base)

    def array(self, property: str) -> ObserverBuilderItemSource:
        """Build a array observer on the item. The item will be an array."""
        self._build(lambda node: TransformedItemSource(typing.cast(AbstractItemSource, node), ArrayItemTransformer.factory(property)))
        return ObserverBuilderItemSource(self.base)

    def getter(self, op: typing.Callable[[ItemValue], ItemValue]) -> ObserverBuilderItemSource:
        """Build a getter on the item. The item will be the result of the getter on the value."""
        self._build(lambda node: ItemSource(op(node.item) if node.item else None))
        return ObserverBuilderItemSource(self.base)

    def get(self, attribute: str) -> ObserverBuilderItemSource:
        """Build an unobserved property value on the item. The item will be the property."""
        return self.getter(operator.attrgetter(attribute))

    def tuple(self, *items: ObserverBuilderItemSource) -> ObserverBuilderItemSource:
        """Build a tuple from a list of items. The item will be a tuple."""
        def make_tuple(node: AbstractItemSource) -> ItemTuple:
            item_sources = [item.base._apply(node) for item in items]
            return ItemTuple(*item_sources)
        self._build(make_tuple)
        return ObserverBuilderItemSource(self.base)

    def constant(self, value: ItemValue) -> ObserverBuilderItemSource:
        """Build a constant value. The item will be the constant."""
        self._build(lambda node: ItemSource(value))
        return ObserverBuilderItemSource(self.base)

    def transform(self, fn: typing.Callable[[ItemValue], ItemValue]) -> ObserverBuilderItemSource:
        """Build a transformer applied to the value. The item will be the transformed item."""
        self._build(lambda node: TransformedItemSource(node, FunctionItemTransformer.factory(fn)))
        return ObserverBuilderItemSource(self.base)

    def flatten(self) -> ObserverBuilderItemSource:
        """Build a flattened list. The item will be the list of all the elements in the list of lists."""
        return self.transform(lambda x: list(itertools.chain(*x)))


class ObserverBuilderItemSequenceSource:
    """The observer builder for item sequence sources."""

    def __init__(self, base: ObserverBuilder):
        self.__base = base

    def _build(self, fn: typing.Callable[[typing.Any], typing.Any]) -> None:
        self.__base._build(fn)

    @property
    def base(self) -> ObserverBuilder:
        return self.__base

    def for_each(self, item: ObserverBuilderItemAction) -> ObserverBuilderItemAction:
        """Perform an action on each item in the sequence."""
        def action(node: AbstractItemSource) -> AbstractAction:
            return typing.cast(AbstractAction, item.base._apply(node))
        self._build(lambda node: ItemSequenceAction(typing.cast(AbstractItemSequenceSource, node), action))
        return ObserverBuilderItemAction(self.base)

    def map(self, item: ObserverBuilderItemSource) -> ObserverBuilderItemSequenceSource:
        """Perform a mapping on each item in the sequence. The items will be a mapping of the input sequence."""
        def action(node: typing.Optional[AbstractItemSource]) -> typing.Optional[AbstractItemSource]:
            return item.base._apply(node)
        self._build(lambda node: MappedItemSequence(typing.cast(AbstractItemSequenceSource, node), action))
        return ObserverBuilderItemSequenceSource(self.base)

    def filter(self, predicate: typing.Callable[[ItemValue], bool]) -> ObserverBuilderItemSequenceSource:
        """Perform a filter on each item in the sequence. The items will be a filtered version of the input sequence."""
        self._build(lambda node: FilteredItemSequence(typing.cast(AbstractItemSequenceSource, node), predicate))
        return ObserverBuilderItemSequenceSource(self.base)

    def trampoline(self, target: Observable.Observable, key: str) -> ObserverBuilderItemAction:
        """Observe the sequence and pass along changes to the target as a sequence."""
        self._build(lambda node: ItemSequenceTrampoline(typing.cast(AbstractItemSequenceSource, node), target, key))
        return ObserverBuilderItemAction(self.base)

    def collect_list(self) -> ObserverBuilderItemSource:
        """Convert the item sequence to a list. The item will be a list of the inputs."""
        self._build(lambda node: ItemSequenceListReducer(typing.cast(AbstractItemSequenceSource, node), ItemSequenceCollector()))
        return ObserverBuilderItemSource(self.base)

    def len(self) -> ObserverBuilderItemSource:
        """Return the length of the sequence."""
        self._build(lambda node: ItemSequenceListReducer(typing.cast(AbstractItemSequenceSource, node), ItemSequenceLength()))
        return ObserverBuilderItemSource(self.base)

    def index(self, index: int) -> ObserverBuilderItemSource:
        """Return the index item in the ordered sequence."""
        self._build(lambda node: ItemSequenceIndex(typing.cast(AbstractItemSequenceSource, node), index))
        return ObserverBuilderItemSource(self.base)

    def sequence_property(self, property: str) -> ObserverBuilderItemSequenceSource:
        self._build(lambda node: TransformedItemSequence(node, PropertyItemTransformer.factory(property)))
        return ObserverBuilderItemSequenceSource(self.base)

    def sequence_array(self, key: str) -> ObserverBuilderItemSequenceSource:
        self._build(lambda node: TransformedItemSequence(node, ArrayItemTransformer.factory(key)))
        return ObserverBuilderItemSequenceSource(self.base)


class ObserverBuilderItemAction:

    def __init__(self, base: ObserverBuilder):
        self.__base = base

    def _build(self, fn: typing.Callable[[typing.Any], typing.Any]) -> None:
        self.__base._build(fn)

    @property
    def base(self) -> ObserverBuilder:
        return self.__base
