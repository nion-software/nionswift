from __future__ import annotations

# standard libraries
import gettext
import operator
import typing

# third party libraries
# None

# local libraries
from nion.swift import ComputationPanel
from nion.swift import EntityBrowser
from nion.swift import Inspector
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Model as DataModel
from nion.swift.model import Schema
from nion.swift.model import Symbolic
from nion.ui import Declarative
from nion.utils import Converter
from nion.utils import ListModel
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.ui import Application

_DocumentControllerWeakRefType = typing.Callable[[], "DocumentController.DocumentController"]

_ = gettext.gettext

T = typing.TypeVar('T')


class DataItemInspectorHandler(Declarative.Handler):
    def __init__(self, context: EntityBrowser.Context, data_item: DataItem.DataItem):
        super().__init__()
        self.context = context
        self.item = data_item
        self.uuid_converter = Converter.UuidToStringConverter()
        self.date_converter = Converter.DatetimeToStringConverter(is_local=True, format="%Y-%m-%d %H:%M:%S %Z")
        u = Declarative.DeclarativeUI()
        label = u.create_label(text=self.item.title)
        uuid_row = u.create_row(u.create_label(text="UUID:", width=60), u.create_label(text="@binding(item.uuid, converter=uuid_converter)"), u.create_stretch(), spacing=12)
        modified_row = u.create_row(u.create_label(text="Modified:", width=60), u.create_label(text="@binding(item.modified, converter=date_converter)"), u.create_label(text="(local)"), u.create_stretch(), spacing=12)
        source_line = [u.create_component_instance("source_component")] if context.values.get("do_references", False) else []
        data_source_chooser = {
            "type": "data_source_chooser",
            "display_item": "@binding(display_item)",
            "min_width": 80,
            "min_height": 80,
        }
        self.ui_view = u.create_column(label,
                                       uuid_row,
                                       modified_row,
                                       *source_line,
                                       data_source_chooser,
                                       u.create_stretch(),
                                       spacing=12)

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        document_model = typing.cast(DocumentModel.DocumentModel, self.context.values["document_model"])
        return document_model.get_best_display_item_for_data_item(self.item)

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "source_component":
            return EntityBrowser.ReferenceHandler(self.context, _("Source"), self.item.source)
        if component_id == "entity_component":
            return EntityBrowser.make_record_handler(self.context, self.item, DataModel.DataItem.entity_id, 0, DataModel.DataItem)
        return None


class DataItemInspectorHandlerFactory(EntityBrowser.ItemInspectorHandlerFactory):
    def make_sections(self, context: EntityBrowser.Context, item: typing.Any) -> typing.Sequence[typing.Tuple[str, Declarative.HandlerLike]]:
        if isinstance(item, DataItem.DataItem):
            return [(_("Data Item"), DataItemInspectorHandler(context, item))]
        return list()


class DisplayItemInspectorHandler(Declarative.Handler):
    def __init__(self, context: EntityBrowser.Context, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()

        self.item = display_item
        self.uuid_converter = Converter.UuidToStringConverter()
        self.date_converter = Converter.DatetimeToStringConverter(is_local=True, format="%Y-%m-%d %H:%M:%S %Z")

        u = Declarative.DeclarativeUI()

        label = u.create_label(text=display_item.title)
        uuid_row = u.create_row(u.create_label(text="UUID:", width=60),
                                u.create_label(text="@binding(item.uuid, converter=uuid_converter)"),
                                u.create_stretch(), spacing=12)
        modified_row = u.create_row(u.create_label(text="Modified:", width=60),
                                    u.create_label(text="@binding(item.modified, converter=date_converter)"),
                                    u.create_label(text="(local)"), u.create_stretch(), spacing=12)

        data_source_chooser = {
            "type": "data_source_chooser",
            "display_item": "@binding(item)",
            "min_width": 80,
            "min_height": 80,
        }

        self.ui_view = u.create_column(label,
                                       uuid_row,
                                       modified_row,
                                       data_source_chooser,
                                       u.create_stretch(),
                                       spacing=12)


class DisplayItemInspectorHandlerFactory(EntityBrowser.ItemInspectorHandlerFactory):
    def make_sections(self, context: EntityBrowser.Context, item: typing.Any) -> typing.Sequence[typing.Tuple[str, Declarative.HandlerLike]]:
        if isinstance(item, DisplayItem.DisplayItem):
            return [(_("Display Item"), DisplayItemInspectorHandler(context, item))]
        return list()


class DataStructureInspectorHandler(Declarative.Handler):
    def __init__(self, context: EntityBrowser.Context, data_structure: DataStructure.DataStructure):
        super().__init__()
        self.context = context
        self.data_structure = data_structure
        self.ui_view = self.__make_ui()
        self.uuid_converter = Converter.UuidToStringConverter()
        self.date_converter = Converter.DatetimeToStringConverter(is_local=True, format="%Y-%m-%d %H:%M:%S %Z")

    def __make_ui(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        label = u.create_label(text=self.data_structure.structure_type)
        uuid_row = u.create_row(u.create_label(text="UUID:", width=60), u.create_label(text="@binding(data_structure.uuid, converter=uuid_converter)"), u.create_stretch(), spacing=12)
        modified_row = u.create_row(u.create_label(text="Modified:", width=60), u.create_label(text="@binding(data_structure.modified, converter=date_converter)"), u.create_label(text="(local)"), u.create_stretch(), spacing=12)
        entity = self.data_structure.entity
        source_line = [u.create_component_instance("source_component")] if self.context.values.get("do_references", False) else []
        if entity and entity.entity_type:
            entity_component = u.create_component_instance("entity_component")
        else:
            label2 = u.create_label(text=entity.entity_type.entity_id if entity else "NO ENTITY")
            label3 = u.create_label(text=str(entity.entity_type._field_type_map) if entity else str(self.data_structure.write_to_dict()["properties"]), max_width=300)
            entity_component = u.create_column(label2, label3, spacing=12)
        return u.create_column(label,
                               uuid_row,
                               modified_row,
                               *source_line,
                               entity_component,
                               u.create_stretch(),
                               spacing=12)

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "source_component":
            return EntityBrowser.ReferenceHandler(self.context, _("Source"), self.data_structure.source)
        if component_id == "entity_component":
            entity = self.data_structure.entity
            assert entity
            # note: use data structure as the base item of the entity field handler since the entity is not quite
            # properly connected to the data structure. setting a value on the data structure does not send a property
            # changed value from the entity.
            return EntityBrowser.make_record_handler(self.context, self.data_structure, entity.entity_type.entity_id, 0, entity.entity_type)
        return None


class DataStructureInspectorHandlerFactory(EntityBrowser.ItemInspectorHandlerFactory):
    def make_sections(self, context: EntityBrowser.Context, item: typing.Any) -> typing.Sequence[typing.Tuple[str, Declarative.HandlerLike]]:
        if isinstance(item, DataStructure.DataStructure):
            return [(_("Data Structure"), DataStructureInspectorHandler(context, item))]
        return list()


class ComputationInspectorHandlerFactory(EntityBrowser.ItemInspectorHandlerFactory):
    def make_sections(self, context: EntityBrowser.Context, item: typing.Any) -> typing.Sequence[typing.Tuple[str, Declarative.HandlerLike]]:
        if isinstance(item, Symbolic.Computation):
            return [
                (_("Edit"), ComputationPanel.ComputationInspectorHandler(context, item)),
                (_("Errors"), ComputationPanel.ComputationErrorInspectorHandler(context, item)),
            ]
        return list()


Registry.register_component(DataItemInspectorHandlerFactory(), {"item-inspector-handler-factory"})
Registry.register_component(DisplayItemInspectorHandlerFactory(), {"item-inspector-handler-factory"})
Registry.register_component(DataStructureInspectorHandlerFactory(), {"item-inspector-handler-factory"})
Registry.register_component(ComputationInspectorHandlerFactory(), {"item-inspector-handler-factory"})


ProjectExtra = Schema.entity("project_extra", None, 3, {
    "title": Schema.prop(Schema.STRING),
    "workspace": Schema.reference(DataModel.Workspace),
    "data_item_references": Schema.map(Schema.STRING, Schema.reference(DataModel.DataItem)),
    "mapped_items": Schema.array(Schema.reference(DataModel.DataItem), Schema.OPTIONAL),
    "project_data_folders": Schema.array(Schema.prop(Schema.PATH)),
})


class ProjectItemsDialog(Declarative.WindowHandler):

    def __init__(self, document_controller: DocumentController.DocumentController) -> None:
        super().__init__()

        self.__document_controller = document_controller

        self.dialog_id = "project_items"

        self.items_model = ListModel.ListModel[EntityBrowser.ProjectItemsEntry]()

        context = Inspector.ComputationInspectorContext(document_controller, self, True)

        self.items_model.append_item(
            EntityBrowser.ProjectItemsEntry(context, _("Computations"), document_controller.document_model,
                                            "computations", DataModel.Computation, _("Computation"), operator.attrgetter("label")))
        self.items_model.append_item(
            EntityBrowser.ProjectItemsEntry(context, _("Data Structures"), document_controller.document_model,
                                            "data_structures", None, _("Data Structure"), operator.attrgetter("structure_type")))
        self.items_model.append_item(
            EntityBrowser.ProjectItemsEntry(context, _("Data Items"), document_controller.document_model, "data_items",
                                            DataModel.DataItem, _("Data Item"), operator.attrgetter("title")))
        self.items_model.append_item(
            EntityBrowser.ProjectItemsEntry(context, _("Display Items"), document_controller.document_model,
                                            "display_items", DataModel.DisplayItem, _("Display Item"), operator.attrgetter("title")))
        self.items_model.append_item(
            EntityBrowser.ProjectItemsEntry(context, _("Connections"), document_controller.document_model,
                                            "connections", DataModel.Connection, _("Connection"), lambda x: str(x.uuid)))
        self.items_model.append_item(
            EntityBrowser.ProjectItemsEntry(context, _("Data Groups"), document_controller.document_model,
                                            "data_groups", DataModel.DataGroup, _("Data Group"), operator.attrgetter("title")))
        self.items_model.append_item(
            EntityBrowser.ProjectItemsEntry(context, _("Projects"),
                                            typing.cast(typing.Any, document_controller.app).profile, "projects",
                                            ProjectExtra, _("Project"), operator.attrgetter("title")))
        self.items_model.append_item(
            EntityBrowser.ProjectItemsEntry(context, _("Workspaces"), document_controller.project, "workspaces",
                                            DataModel.Workspace, _("Workspace"), operator.attrgetter("name")))

        # close any previous list dialog associated with the window
        previous_window = getattr(document_controller, f"_{self.dialog_id}_dialog", None)
        if isinstance(previous_window, ProjectItemsDialog):
            previous_window.close_window()
        setattr(document_controller, f"_{self.dialog_id}_dialog", self)

        self.__master_detail_handler = EntityBrowser.MasterDetailHandler(self.items_model, "items", typing.cast(EntityBrowser.DynamicWidgetConstructorFn, EntityBrowser.ProjectItemsContent), operator.attrgetter("label"))

        u = Declarative.DeclarativeUI()

        window = u.create_window(u.create_component_instance(identifier="content"), title=_("Project Items (Computations)"), margin=12, window_style="tool")
        self.run(window, parent_window=document_controller, persistent_id=self.dialog_id)
        self.__document_controller.register_dialog(self.window)

    def close(self) -> None:
        setattr(self.__document_controller, f"_{self.dialog_id}_dialog", None)
        super().close()

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "content":
            return self.__master_detail_handler
        return None

    @property
    def document_model(self) -> DocumentModel.DocumentModel:
        return self.__document_controller.document_model

    def open_project_item(self, item: typing.Any) -> None:
        class Visitor(Schema.Visitor):
            def __init__(self, base_value: typing.Any) -> None:
                self.base_value = base_value
                self.breadcrumbs: typing.Sequence[typing.Any] = list()

            def visit(self, accessor: Schema.Accessor) -> None:
                value = accessor.get_value(self.base_value)
                if value == item and isinstance(accessor.field_type, Schema.ComponentType):
                    self.breadcrumbs = accessor.breadcrumbs(self.base_value)

        project = self.__document_controller.project
        visitor = Visitor(project)
        DataModel.Project.visit(typing.cast(Schema.Entity, project), Schema.BaseAccessor(Schema.reference(DataModel.Project), "project"), visitor)

        for index, project_items in enumerate(self.items_model.items):
            for value in reversed(visitor.breadcrumbs):
                if value in project_items.model.items:
                    self.__master_detail_handler.index_model.value = index
                    item_index = project_items.model.items.index(value)
                    detail_component = typing.cast(EntityBrowser.DynamicHandler, self.__master_detail_handler._detail_components[self.items_model._items[self.__master_detail_handler.index_model.value]])
                    assert detail_component.dynamic_widget and detail_component.dynamic_widget.dynamic_handler
                    content_handler = typing.cast(EntityBrowser.ProjectItemsContent, detail_component.dynamic_widget.dynamic_handler)
                    detail_handler = typing.cast(EntityBrowser.MasterDetailHandler, content_handler._master_detail_handler)
                    detail_handler.index_model.value = item_index
                    return


def make_project_items_dialog(document_controller: DocumentController.DocumentController) -> None:
    ProjectItemsDialog(document_controller)
