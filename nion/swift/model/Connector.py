# standard libraries
import abc
import functools
import typing

# third party libraries
# None

# local libraries
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Observable


class PropertyConnectorItem:

    def __init__(self, item: Observable.Observable, property_name: str, converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]] = None) -> None:
        self.item = item
        self.property_name = property_name
        self.converter = converter

    def get_common_value(self) -> typing.Any:
        value = getattr(self.item, self.property_name)
        return self.converter.convert(value) if self.converter else value

    def set_common_value(self, formatted_value: typing.Any) -> None:
        value = self.converter.convert_back(formatted_value) if self.converter else formatted_value
        setattr(self.item, self.property_name, value)


class PropertyConnector:
    # the converter converts from the internal property to common property.
    # when a property change is received, it converts back to the common property.
    # when a common property is sent out to other items it is converted from the
    # common property.

    def __init__(self, property_connector_items: typing.Sequence[PropertyConnectorItem]) -> None:
        self.__property_changed_listeners: typing.List[Event.EventListener] = list()

        self.__suppress = False

        def property_changed(property_connector_item: PropertyConnectorItem, key: str) -> None:
            if not self.__suppress:
                self.__suppress = True
                try:
                    if key == property_connector_item.property_name:
                        common_value = property_connector_item.get_common_value()
                        for i_property_connector_item in property_connector_items:
                            if i_property_connector_item != property_connector_item:
                                i_property_connector_item.set_common_value(common_value)
                finally:
                    self.__suppress = False

        for property_connector_item in property_connector_items:
            self.__property_changed_listeners.append(property_connector_item.item.property_changed_event.listen(functools.partial(property_changed, property_connector_item)))

        property_changed(property_connector_items[0], property_connector_items[0].property_name)

    def close(self) -> None:
        for listener in self.__property_changed_listeners:
            listener.close()
        self.__property_changed_listeners = typing.cast(typing.List[Event.EventListener], None)
