"""
Provide tools for a general entity browser.

An entity is defined by a schema and this set of UI elements facilitates a master-detail hierarchy to browse
entities (aka items/objects) that adhere to that schema.
"""

from __future__ import annotations

# standard libraries
import asyncio
import dataclasses
import gettext
import operator
import typing

# third party libraries
# None

# local libraries
from nion.swift.model import Schema
from nion.ui import Declarative
from nion.ui import UserInterface
from nion.ui import Widgets
from nion.ui import Window
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import ListModel
from nion.utils import Model
from nion.utils import Observable
from nion.utils import Registry
from nion.utils.ReferenceCounting import weak_partial

_ = gettext.gettext

T = typing.TypeVar('T')

INDENT = 8
LABEL_WIDTH = 100


class ReferenceHandlerContext(typing.Protocol):
    def open_project_item(self, item: typing.Any) -> None: ...


@dataclasses.dataclass
class Context:
    values: typing.Dict[str, typing.Any] = dataclasses.field(default_factory=dict)


class ReferenceHandler(Declarative.Handler):
    def __init__(self, context: Context, label: str, item: typing.Optional[typing.Any]) -> None:
        super().__init__()
        self.context = context
        self.label = label
        self.item = item
        self.ui_view = self.__make_ui()

    def __make_ui(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        if self.item:
            label = u.create_label(text=self.item.__class__.__name__)
            link = u.create_push_button(text="\N{RIGHTWARDS BLACK ARROW}", on_clicked="handle_link",
                                        border_color="transparent", background_color="rgba(0,0,0,0.0)", style="minimal",
                                        size_policy_horizontal="maximum")
            label_section = u.create_row(label, link)
        else:
            label_section = u.create_label(text=_("None [reference]"))
        return u.create_row(
            u.create_label(text=self.label, tool_tip=self.label, width=LABEL_WIDTH),
            label_section,
            u.create_stretch(),
            spacing=12)

    def handle_link(self, item: Declarative.UIWidget) -> None:
        if self.item:
            reference_handler = typing.cast(typing.Optional[ReferenceHandlerContext], self.context.values.get("reference_handler", None))
            if reference_handler:
                reference_handler.open_project_item(self.item)


class ItemToStringConverter(Converter.ConverterLike[typing.Any, str]):
    def convert(self, value: typing.Optional[typing.Any]) -> typing.Optional[str]:
        return f"{str(value)}" if value else _("<empty>")

    def convert_back(self, formatted_value: typing.Optional[str]) -> typing.Optional[typing.Any]:
        return str()


class EntityPropertyHandler(Declarative.Handler):
    def __init__(self, name: str, value_type: Schema.PropertyType, value_model: Model.PropertyModel[typing.Any]) -> None:
        super().__init__()
        self.value_model = value_model
        self.ui_view = self._make_ui(name, value_type)
        self.int_converter = Converter.IntegerToStringConverter()
        self.float_converter = Converter.FloatToStringConverter()
        self.date_converter = Converter.DatetimeToStringConverter(is_local=True, format="%Y-%m-%d %H:%M:%S %Z")
        self.uuid_converter = Converter.UuidToStringConverter()
        self.str_converter = ItemToStringConverter()

    def _make_ui(self, name: str, value_type: Schema.PropertyType) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        if value_type.type == Schema.STRING:
            return u.create_row(u.create_label(text=name, tool_tip=name, width=LABEL_WIDTH),
                                u.create_label(text=f"@binding(value_model.value, converter=str_converter)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.BOOLEAN:
            return u.create_row(u.create_label(text=name, tool_tip=name, width=LABEL_WIDTH),
                                u.create_check_box(text=f"@binding(value_model.value)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.INT:
            return u.create_row(u.create_label(text=name, tool_tip=name, width=LABEL_WIDTH),
                                u.create_label(text=f"@binding(value_model.value, converter=int_converter)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.FLOAT:
            return u.create_row(u.create_label(text=name, tool_tip=name, width=LABEL_WIDTH),
                                u.create_label(text=f"@binding(value_model.value, converter=float_converter)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.TIMESTAMP:
            return u.create_row(u.create_label(text=name, tool_tip=name, width=LABEL_WIDTH),
                                u.create_label(text=f"@binding(value_model.value, converter=date_converter)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type == Schema.UUID:
            return u.create_row(u.create_label(text=name, tool_tip=name, width=LABEL_WIDTH),
                                u.create_label(text=f"@binding(value_model.value, converter=uuid_converter)"),
                                u.create_stretch(), spacing=12)
        elif value_type.type in (Schema.DICT, Schema.LIST, Schema.SET):
            return u.create_row(u.create_label(text=name, tool_tip=name, width=LABEL_WIDTH),
                                u.create_row(
                                    u.create_label(text=f"{value_type.type}: "),
                                    u.create_label(text=f"@binding(value_model.value, converter=str_converter)"),
                                ),
                                u.create_stretch(),
                                spacing=12)
        NOT_DISPLAYED = _("not displayed")
        return u.create_row(u.create_label(text=name, tool_tip=name, width=LABEL_WIDTH),
                            u.create_label(text=f"{value_type.type} ({NOT_DISPLAYED})"),
                            u.create_stretch(),
                            spacing=12)


class EntityTupleModel(Observable.Observable):
    # takes a property model and generates item inserted/removed events when the value changes.
    # observers can treat this as a dynamic list with 'items' key.

    def __init__(self, value_model: Model.PropertyModel[typing.Any]) -> None:
        super().__init__()
        self.items: typing.List[typing.Any] = list()

        def property_changed(tuple_model: EntityTupleModel, property_name: str) -> None:
            # check if changed property matches property name for this object
            if property_name == "value":
                while tuple_model.items:
                    item = tuple_model.items.pop()
                    tuple_model.notify_remove_item("items", item, len(tuple_model.items))
                items = typing.cast(typing.List[typing.Any], value_model.value)
                for index, item in enumerate(items or tuple()):
                    tuple_model.items.append((index, item))
                    tuple_model.notify_insert_item("items", tuple_model.items[-1], len(tuple_model.items))

        self.__listener = value_model.property_changed_event.listen(weak_partial(property_changed, self))

        property_changed(self, "value")


class EntityTupleHandler(Declarative.Handler):
    def __init__(self, context: Context, name: str, value_type: Schema.FieldType, value_model: Model.PropertyModel[typing.Any]) -> None:
        super().__init__()
        self.context = context
        self.value_model = value_model
        self.value_type = value_type
        self.tuple_model = EntityTupleModel(value_model)
        u = Declarative.DeclarativeUI()
        # the items in tuple_model (tuples an index and a value of value_type) will get passed to create_handler in the
        # item parameter. this is accomplished by passing items to create_column below. the item_component_id is
        # used to match this column with the request for a handler.
        self.ui_view = u.create_column(
            u.create_row(u.create_label(text=name), u.create_stretch()),
            u.create_row(u.create_spacing(INDENT), u.create_column(items="tuple_model.items", item_component_id="entity_field", spacing=8)),
            spacing = 8,
        )

    def create_handler(self, component_id: str, container: typing.Optional[ListModel.ListModel[typing.Any]] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        # item is a tuple of type index, self.value_type
        if component_id == "entity_field" and item is not None:
            index, item_ = item
            return make_field_handler(self.context, str(index), self.value_type, Model.PropertyModel(item_))
        return None


class EntityArrayHandler(Declarative.Handler):
    def __init__(self, context: Context, name: str, value_type: Schema.FieldType, value_model: Model.PropertyModel[typing.Any]) -> None:
        super().__init__()
        self.context = context
        self.value_model = value_model
        self.value_type = value_type
        self.tuple_model = EntityTupleModel(value_model)
        u = Declarative.DeclarativeUI()
        # the items in tuple_model (tuples an index and a value of value_type) will get passed to create_handler in the
        # item parameter. this is accomplished by passing items to create_column below. the item_component_id is
        # used to match this column with the request for a handler.
        self.ui_view = u.create_column(
            u.create_row(u.create_label(text=name), u.create_stretch()),
            u.create_row(u.create_spacing(INDENT), u.create_column(items="tuple_model.items", item_component_id="entity_field", spacing=8)),
            spacing = 8,
        )

    def create_handler(self, component_id: str, container: typing.Optional[ListModel.ListModel[typing.Any]] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        # item is a tuple of type index, self.value_type
        if component_id == "entity_field" and item is not None:
            index, item_ = item
            return make_field_handler(self.context, str(index), self.value_type, Model.PropertyModel(item_), display_component_type=True)
        return None


class EntityValueIndexModel(Model.PropertyModel[T], typing.Generic[T]):
    # NOTE: read only

    def __init__(self, value_model: Model.PropertyModel[T], index: int) -> None:
        assert value_model.value is not None
        super().__init__(getattr(value_model, "value")[index])
        self.__value_model = value_model

        def property_changed(property_model: EntityValueIndexModel[T], value_model: Model.PropertyModel[T], property_name: str) -> None:
            # check if changed property matches property name for this object
            if property_name == "value":
                property_model.value = getattr(value_model, property_name)[index]

        self.__listener = self.__value_model.property_changed_event.listen(weak_partial(property_changed, self, self.__value_model))


class EntityFieldsHandler(Declarative.Handler):
    def __init__(self, context: Context, name: str, field_list: typing.Sequence[typing.Tuple[str, Schema.FieldType, Model.PropertyModel[typing.Any]]], *, component_type: typing.Optional[str] = None) -> None:
        super().__init__()
        self.context = context
        self.field_list = list(field_list)
        u = Declarative.DeclarativeUI()
        # the items in field_list (field-name/value-type/property-model) will get passed to create_handler in the
        # item parameter. this is accomplished by passing items to create_column below. the item_component_id is
        # used to match this column with the request for a handler.
        component_type_row = u.create_row(u.create_label(text=_("type"), width=LABEL_WIDTH), u.create_label(text=component_type), u.create_stretch(), spacing=12)
        self.ui_view = u.create_column(
            u.create_row(u.create_label(text=name), u.create_stretch()),
            u.create_row(
                u.create_spacing(INDENT),
                u.create_column(
                    *([component_type_row] if component_type else []),
                    u.create_row(u.create_column(items="field_list", item_component_id="entity_field", spacing=8)),
                    spacing=8
                ),
            ),
            spacing = 8,
        )

    def create_handler(self, component_id: str, container: typing.Optional[typing.Any] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        # item is a tuple of field name, value type, and value model. it comes from the field list passed during init.
        if component_id == "entity_field" and item is not None:
            field_name, value_type, value_model = typing.cast(typing.Tuple[str, Schema.FieldType, Model.PropertyModel[typing.Any]], item)
            return make_field_handler(self.context, field_name, value_type, value_model)
        return None


class MaybePropertyChangedPropertyModel(Model.PropertyModel[typing.Any]):
    """Observes a property on another item and makes it a standard property model.

    When the observed property changes, update this value.

    When this value changes, update the observed property.
    """

    def __init__(self, observable: Observable.Observable, property_name: str) -> None:
        super().__init__(getattr(observable, property_name, None))
        self.__observable = observable
        self.__property_name = property_name

        def property_changed(property_model: MaybePropertyChangedPropertyModel, observable: Observable.Observable, property_name: str, property_name_: str) -> None:
            # check if changed property matches property name for this object
            if property_name_ == property_name:
                property_model.value = getattr(observable, property_name)

        if hasattr(self.__observable, "property_changed_event"):
            self.__listener = self.__observable.property_changed_event.listen(weak_partial(property_changed, self, observable, property_name))

    def _set_value(self, value: typing.Optional[T]) -> None:
        super()._set_value(value)
        # set the property on the observed object. this will trigger a property changed, but will be ignored since
        # the value doesn't change.
        setattr(self.__observable, self.__property_name, value)


class DummyHandler(Declarative.HandlerLike):
    def __init__(self, field_name: str, text: str) -> None:
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_row(u.create_label(text=field_name, tool_tip=field_name, width=LABEL_WIDTH), u.create_label(text=text), u.create_stretch(), spacing=12)

    def close(self) -> None:
        pass


class HasFieldTypeMap(typing.Protocol):
    @property
    def _field_type_map(self) -> typing.Mapping[str, Schema.FieldType]: raise NotImplementedError()


def make_record_handler(context: Context, item: Observable.Observable, name: str, entity_type: HasFieldTypeMap, *, display_component_type: bool = False) -> EntityFieldsHandler:
    field_list = [(n, t, MaybePropertyChangedPropertyModel(item, n)) for n, t in entity_type._field_type_map.items()]
    return EntityFieldsHandler(context, name, field_list, component_type=getattr(entity_type, "entity_id", None))


def make_field_handler(context: Context, field_name: str, value_type: Schema.FieldType, value_model: Model.PropertyModel[typing.Any], *, display_component_type: bool = False) -> typing.Optional[Declarative.HandlerLike]:
    # when item type is property type, create an entity property handler, passing the value type and property model directly.
    if isinstance(value_type, Schema.PropertyType):
        return EntityPropertyHandler(field_name, value_type, value_model)

    # when item type is tuple type, create an entity tuple handler, passing the value type of the tuple and the property model directly.
    # the tuple handler will watch for changes to the property model and update its internal list accordingly.
    if isinstance(value_type, Schema.TupleType):
        return EntityTupleHandler(context, field_name, value_type.type, value_model)

    # when item type is fixed tuple type, make a list of field-name/value-type/property-model tuples, creating
    # entity value index models to access the individual fields, and recursively create another entity fields
    # handler with the list.
    if isinstance(value_type, Schema.FixedTupleType):
        if value_model.value is not None:
            field_list = [(str(i), t, EntityValueIndexModel(value_model, i)) for i, t in enumerate(value_type.types)]
            return EntityFieldsHandler(context, field_name, field_list)
        else:
            return DummyHandler(field_name, "NONE [fixed-tuple]")

    # when item type is record type, use make_record_handler to where the item is the value of the value_model passed
    # to this function.
    if isinstance(value_type, Schema.RecordType):
        if value_model.value is not None:
            return make_record_handler(context, value_model.value, field_name, value_type)
        else:
            return DummyHandler(field_name, "NONE [record]")

    # when item type is array type, create an entity array handler, passing the value type of the array and the property model directly.
    # the array handler will watch for changes to either the property model or the list value of the property model and update its
    # internal list accordingly.
    if isinstance(value_type, Schema.ArrayType):
        return EntityArrayHandler(context, field_name, value_type.type, value_model)

    # map

    # reference is only used if allowed in the context.
    if isinstance(value_type, Schema.ReferenceType):
        if context.values.get("do_references", False):
            return ReferenceHandler(context, field_name, value_model.value)

    # when item type is component type, use make_record_handler to where the item is the value of the value_model passed
    # to this function. get the entity type from the component type.
    if isinstance(value_type, Schema.ComponentType):
        if value_model.value is not None:
            entity_type = Schema.get_entity_type(value_type.entity_id)
            # hack to handle subclasses; look at the value itself and figure out the type if possible.
            if value_model.value and hasattr(value_model.value, "type") and value_model.value.type != value_type.entity_id:
                entity_type = Schema.entity_types.get(value_model.value.type, entity_type)
            assert entity_type
            return make_record_handler(context, value_model.value, field_name, entity_type, display_component_type=display_component_type)
        else:
            return DummyHandler(field_name, "NONE [component]")

    # fall through to a dummy handler.
    return DummyHandler(field_name, str(value_type))


class ItemInspectorHandlerFactory(typing.Protocol):
    def make_sections(self, context: Context, item: typing.Any) -> typing.Sequence[typing.Tuple[str, Declarative.HandlerLike]]: ...


class ItemPageHandler(Declarative.Handler):
    def __init__(self,
                 context: Context,
                 item: typing.Any,
                 entity_type: typing.Optional[Schema.EntityType],
                 title: str,
                 item_title_getter: typing.Optional[typing.Callable[[typing.Any], str]] = None) -> None:
        super().__init__()
        self.context = context
        self.item = item
        self.__title = title
        self.__entity_type = entity_type
        self.__item_title_getter = item_title_getter
        self.__handlers: typing.List[Declarative.HandlerLike] = list()
        self.uuid_converter = Converter.UuidToStringConverter()
        self.date_converter = Converter.DatetimeToStringConverter(is_local=True, format="%Y-%m-%d %H:%M:%S %Z")
        self.ui_view = self._make_ui()

    def _make_ui(self) -> Declarative.UIDescriptionResult:
        tabs: typing.List[Declarative.UIDescription] = list()
        item_inspector_sections: typing.List[typing.Tuple[str, Declarative.HandlerLike]] = list()
        for component in Registry.get_components_by_type("item-inspector-handler-factory"):
            item_inspector_handler_factory = typing.cast(ItemInspectorHandlerFactory, component)
            item_inspector_sections.extend(item_inspector_handler_factory.make_sections(self.context, self.item))
        u = Declarative.DeclarativeUI()
        for index, (title, handler) in enumerate(item_inspector_sections):
            handler_index = len(self.__handlers)
            self.__handlers.append(handler)
            tabs.append(u.create_tab(title, u.create_component_instance(f"handler_{handler_index}")))
        if self.__entity_type:
            entity_component = u.create_scroll_area(u.create_column(u.create_component_instance("entity_component"), u.create_stretch()))
            tabs.append(u.create_tab(_("Details"), entity_component))
        return u.create_tabs(*tabs, style="minimal")

    def create_handler(self, component_id: str, container: typing.Optional[typing.Any] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "entity_component":
            # hack to handle subclasses; look at the value itself and figure out the type if possible.
            entity_type = self.__entity_type
            assert entity_type
            if self.item and hasattr(self.item, "type") and self.item.type != entity_type.entity_id:
                entity_type = Schema.entity_types.get(self.item.type, entity_type)
                assert entity_type
            return make_record_handler(self.context, self.item, entity_type.entity_id, entity_type)
        for handler_index, handler in enumerate(self.__handlers):
            if component_id == f"handler_{handler_index}":
                return handler
        return None


DynamicWidgetConstructorFn = typing.Callable[[typing.Any], typing.Optional[Declarative.HandlerLike]]


class DynamicWidget(UserInterface.Widget):
    """Widget which only adds content when the produce when produce_widget is called."""
    def __init__(self, ui: UserInterface.UserInterface, event_loop: asyncio.AbstractEventLoop, component_fn: DynamicWidgetConstructorFn) -> None:
        self.__ui = ui
        self.__event_loop = event_loop
        self.__component_fn = component_fn
        self.__widget = ui.create_column_widget()
        super().__init__(Widgets.CompositeWidgetBehavior(self.__widget))
        self.__handler: typing.Optional[Declarative.HandlerLike] = None

    @property
    def dynamic_handler(self) -> typing.Optional[Declarative.HandlerLike]:
        return self.__handler

    def produce_widget(self, item: typing.Any) -> None:
        if self.__widget.child_count == 0:
            self.__handler = self.__component_fn(item)
            if self.__handler:
                self.__widget.add(Declarative.DeclarativeWidget(self.__ui, self.__event_loop, self.__handler))


class DynamicHandler(Declarative.Handler):
    """Dynamic handler which contains a dynamic widget and only makes the widget when produce_widget is called."""
    def __init__(self, item: typing.Any, component_fn: DynamicWidgetConstructorFn) -> None:
        super().__init__()
        self.__item = item
        self.component_fn = component_fn
        self.ui_view = {"type": "dynamic", "name": "dynamic_widget"}
        self.dynamic_widget: typing.Optional[DynamicWidget] = None

    def produce_widget(self) -> None:
        if self.dynamic_widget:
            self.dynamic_widget.produce_widget(self.__item)


class DynamicDeclarativeWidgetConstructor:
    def construct(self, d_type: str, ui: UserInterface.UserInterface, window: typing.Optional[Window.Window],
                  d: Declarative.UIDescription, handler: Declarative.HandlerLike,
                  finishes: typing.List[typing.Callable[[], None]]) -> typing.Optional[UserInterface.Widget]:
        if d_type == "dynamic":
            assert window
            widget = DynamicWidget(ui, window.event_loop, typing.cast(DynamicHandler, handler).component_fn)
            if "name" in d:
                setattr(handler, d["name"], widget)
            return widget
        return None


Registry.register_component(DynamicDeclarativeWidgetConstructor(), {"declarative_constructor"})


class MasterDetailHandler(Declarative.Handler):

    def __init__(self, model: Observable.Observable, items_key: str, component_fn: DynamicWidgetConstructorFn,
                 title_getter: typing.Callable[[typing.Any], str]) -> None:
        super().__init__()

        self.__component_fn = component_fn

        # the items for which the details are displayed.
        self.items_model = model

        self.titles_model = ListModel.MappedListModel(container=self.items_model,
                                                      master_items_key=items_key,
                                                      map_fn=title_getter)

        self.__labels_property_model = ListModel.ListPropertyModel(self.titles_model)

        # set up a shadow list following the model/items_key

        def make_shadow(item: typing.Any) -> typing.Any:
            return DynamicHandler(item, component_fn)

        self.shadow_items = ListModel.MappedListModel(container=self.items_model,
                                                      master_items_key=items_key,
                                                      map_fn=make_shadow)

        # the selected item in the items_model
        self.index_model = Model.PropertyModel(0)

        u = Declarative.DeclarativeUI()

        item_list = u.create_list_box(items_ref="@binding(titles_model.items)",
                                      current_index="@binding(index_model.value)",
                                      width=160, min_height=480,
                                      size_policy_vertical="expanding")

        item_stack = u.create_stack(items=f"items_model.{items_key}", item_component_id="detail", current_index="@binding(index_model.value)")

        self.ui_view = u.create_row(u.create_column(item_list), u.create_column(item_stack), spacing=12)

        self._detail_components: typing.Dict[typing.Any, typing.Optional[Declarative.HandlerLike]] = dict()

        def index_changed(property: str) -> None:
            if property == "value":
                self.__update_dynamic_widget()

        self.__listener = self.index_model.property_changed_event.listen(index_changed)

    def __update_dynamic_widget(self) -> None:
        index = self.index_model.value or 0
        if 0 <= index < len(self.shadow_items.items):
            typing.cast(DynamicHandler, self.shadow_items.items[index]).produce_widget()

    def init_handler(self) -> None:
        self.__update_dynamic_widget()

    def create_handler(self, component_id: str, container: typing.Optional[ListModel.ListModel[Declarative.HandlerLike]] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "detail":
            assert container
            handler = typing.cast(Declarative.HandlerLike, self.shadow_items.items[container.items.index(item)])
            self._detail_components[item] = handler
            return handler
        return None

    def get_binding(self, source: Observable.Observable, property: str, converter: typing.Optional[Converter.ConverterLike[typing.Any, typing.Any]]) -> typing.Optional[Binding.Binding]:
        if source == self.titles_model and property == "items":
            return Binding.PropertyBinding(self.__labels_property_model, "value", converter=converter)
        return None


class EntityBrowserEntry:
    def __init__(self, context: Context, title: str, document_model: Observable.Observable,
                 master_items_key: str, entity_type: typing.Optional[Schema.EntityType], title2: str,
                 title_getter: typing.Callable[[typing.Any], str]) -> None:
        model = ListModel.FilteredListModel(container=document_model, master_items_key=master_items_key)
        model.sort_key = operator.attrgetter("modified")
        model.sort_reverse = True
        self.model = model
        self.items_key = "items"

        def create_handler(item: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
            used_entity_type = entity_type if entity_type else (item.entity.entity_type if getattr(item, "entity", None) else None)
            return ItemPageHandler(context, item, used_entity_type, title2, title_getter)

        self.component_fn = create_handler
        self.title_getter = title_getter
        self.label = title


def make_master_detail(project_item_handler: EntityBrowserEntry) -> Declarative.HandlerLike:
    return MasterDetailHandler(project_item_handler.model, project_item_handler.items_key, project_item_handler.component_fn, project_item_handler.title_getter)


class TopLevelItemHandler(Declarative.Handler):
    # a master-detail for each top level item

    def __init__(self, item: typing.Any) -> None:
        super().__init__()
        self.__item = item
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_component_instance(identifier="content")
        self._master_detail_handler = make_master_detail(self.__item)

    def create_handler(self, component_id: str, container: typing.Optional[typing.Any] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "content":
            return self._master_detail_handler
        return None


def open_project_item(entity_browser_component: Declarative.HandlerLike, base_item: typing.Any, base_type: Schema.EntityType, base_name: str, item: typing.Any) -> None:
    """In the entity browser component, focus the item, contained within base_item having type base_type."""

    entity_browser_component = typing.cast(MasterDetailHandler, entity_browser_component)

    class Visitor(Schema.Visitor):
        def __init__(self, base_value: typing.Any) -> None:
            self.base_value = base_value
            self.breadcrumbs: typing.Sequence[typing.Any] = list()

        def visit(self, accessor: Schema.Accessor) -> None:
            value = accessor.get_value(self.base_value)
            if value == item and isinstance(accessor.field_type, Schema.ComponentType):
                self.breadcrumbs = accessor.breadcrumbs(self.base_value)

    visitor = Visitor(base_item)
    base_type.visit(typing.cast(Schema.Entity, base_item), Schema.BaseAccessor(Schema.reference(base_type), base_name),
                    visitor)

    list_model = typing.cast(ListModel.ListModel[EntityBrowserEntry], entity_browser_component.items_model)
    for index, project_items in enumerate(list_model.items):
        for value in reversed(visitor.breadcrumbs):
            if value in project_items.model.items:
                entity_browser_component.index_model.value = index
                item_index = project_items.model.items.index(value)
                detail_component = typing.cast(DynamicHandler, entity_browser_component._detail_components[
                    list_model._items[entity_browser_component.index_model.value]])
                assert detail_component.dynamic_widget and detail_component.dynamic_widget.dynamic_handler
                content_handler = typing.cast(TopLevelItemHandler, detail_component.dynamic_widget.dynamic_handler)
                detail_handler = typing.cast(MasterDetailHandler, content_handler._master_detail_handler)
                detail_handler.index_model.value = item_index
                return


def make_entity_browser_component(items: typing.Sequence[EntityBrowserEntry]) -> Declarative.HandlerLike:
    """Make an entity browser component with the top level items."""

    list_model = ListModel.ListModel[EntityBrowserEntry](items=items)
    return MasterDetailHandler(list_model, "items", typing.cast(DynamicWidgetConstructorFn, TopLevelItemHandler), operator.attrgetter("label"))
