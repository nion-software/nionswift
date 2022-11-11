from __future__ import annotations

# standard libraries
import functools
import gettext
import pathlib
import subprocess
import sys
import typing

# local libraries
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift.model import DataGroup
from nion.swift.model import Profile
from nion.swift.model import Observer
from nion.ui import Dialog
from nion.ui import DrawingContext
from nion.ui import UserInterface
from nion.ui import Window
from nion.ui import Widgets
from nion.utils import Binding
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Observable
from nion.utils import Selection

if typing.TYPE_CHECKING:
    from nion.swift import Application
    from nion.swift import DocumentController
    from nion.swift.model import Persistence

_ = gettext.gettext


def reveal_project(project_reference: Profile.ProjectReference) -> None:
    project_path = project_reference.path
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(project_path)])
    elif sys.platform == 'win32':
        subprocess.run(['explorer', str(project_path.parent)])
    elif sys.platform == 'linux':
        subprocess.check_call(['xdg-open', '--', str(project_path.parent)])


def open_location(location: pathlib.Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(location)])
    elif sys.platform == 'win32':
        subprocess.run(['explorer', str(location)])
    elif sys.platform == 'linux':
        subprocess.check_call(['xdg-open', '--', str(location)])


class ProjectCounterDisplayItem:

    def __init__(self, project_reference: Profile.ProjectReference):
        self.__project_reference = project_reference

        self.__count = 0
        self.on_title_changed: typing.Optional[typing.Callable[[str], None]] = None

        def count_changed(count: Observer.ItemValue) -> None:
            self.__count = count
            if callable(self.on_title_changed):
                self.on_title_changed(self.title)

        oo = Observer.ObserverBuilder()
        oo.source(self.__project_reference).prop("project").sequence_from_array("display_items").len().action_fn(count_changed)
        self.__count_observer = typing.cast(Observer.AbstractItemSource, oo.make_observable())

    def close(self) -> None:
        self.__count_observer.close()
        self.__count_observer = typing.cast(typing.Any, None)
        self.__project_reference = typing.cast(typing.Any, None)
        self.on_title_changed = None

    @property
    def project_reference(self) -> Profile.ProjectReference:
        return self.__project_reference

    @property
    def title(self) -> str:
        return f"{self.__project_reference.title} ({self.__count})"


class CollectionDisplayItemCounter:

    def __init__(self, base_title: str, data_group: typing.Optional[DataGroup.DataGroup], filter_id: typing.Optional[str], document_controller: DocumentController.DocumentController):
        self.__base_title = base_title
        self.__data_group = data_group
        self.__filter_id = filter_id
        self.__filter_predicate = document_controller.get_filter_predicate(filter_id) if self.__filter_id else ListModel.Filter(True)
        self.on_title_changed: typing.Optional[typing.Callable[[str], None]] = None
        self.__count = 0

        # useful for drag and drop
        self.document_controller = document_controller
        self.document_model = document_controller.document_model

        container = self.__data_group or document_controller.document_model

        def count_changed(count: Observer.ItemValue) -> None:
            self.__count = count
            if callable(self.on_title_changed):
                self.on_title_changed(self.title)

        oo = Observer.ObserverBuilder()
        oo.source(container).sequence_from_array("display_items", predicate=self.__filter_predicate.matches).len().action_fn(count_changed)
        self.__count_observer = typing.cast(Observer.AbstractItemSource, oo.make_observable())

    def close(self) -> None:
        self.on_title_changed = None
        self.__count_observer.close()
        self.__count_observer = typing.cast(typing.Any, None)
        self.__data_group = None
        self.document_controller = typing.cast(typing.Any, None)
        self.document_model = typing.cast(typing.Any, None)

    @property
    def title(self) -> str:
        return f"{self.__base_title} ({self.__count})"

    @property
    def is_smart_collection(self) -> bool:
        return not isinstance(self.__data_group, DataGroup.DataGroup)

    @property
    def filter_id(self) -> typing.Optional[str]:
        return self.__filter_id

    @property
    def data_group(self) -> typing.Optional[DataGroup.DataGroup]:
        return self.__data_group


class ProjectPanelItemLike(typing.Protocol):
    folder_key: str
    indent: int
    is_folder: bool


class ProjectPanelProjectItem(ProjectPanelItemLike):

    def __init__(self, indent: int, project_reference: Profile.ProjectReference, display_item_controller: ProjectCounterDisplayItem):
        self.is_folder = False
        self.indent = indent
        self.project_reference = project_reference
        self.display_item_controller = display_item_controller
        self.folder_key = str()

    @property
    def __state_str(self) -> str:
        project_reference = self.project_reference
        project_version = project_reference.project_version
        project_state = project_reference.project_state
        if project_state == "loaded":
            return f"(loaded [v{project_version}])"
        elif project_state == "unloaded":
            return f"(unloaded)"
        elif project_state == "needs_upgrade":
            return f"(needs upgrade [v{project_version}])"
        else:
            return f"(invalid)"

    def __str__(self) -> str:
        icon = "\N{CARD FILE BOX}"
        return f"{icon} {self.display_item_controller.title} {self.__state_str}"
        # NOTE: {DIRECT HIT} is the target icon

    @property
    def is_enabled(self) -> bool:
        return self.project_reference.project is not None and self.project_reference.project.project_state == "loaded"


class ProjectPanelFolderItem(ProjectPanelItemLike):

    def __init__(self, node: TreeNode, indent: int, folder_name: str, folder_closed: bool, folder_key: str):
        self.node = node
        self.is_folder = True
        self.indent = indent
        self.folder_name = folder_name
        self.folder_closed = folder_closed
        self.folder_key = folder_key
        self.is_enabled = False
        self.project_reference = None

    def __str__(self) -> str:
        if sys.platform == "win32":
            triangle_right = "\N{BLACK MEDIUM RIGHT-POINTING TRIANGLE CENTRED}"
            triangle_down = "\N{BLACK MEDIUM DOWN-POINTING TRIANGLE CENTRED}"
        else:
            triangle_right = "\N{BLACK RIGHT-POINTING TRIANGLE}"
            triangle_down = "\N{BLACK DOWN-POINTING TRIANGLE}"
        if self.folder_closed:
            return f"{triangle_right} \N{FILE FOLDER} {self.folder_name}"
        else:
            return f"{triangle_down} \N{OPEN FILE FOLDER} {self.folder_name}"


class TreeNode:

    def __init__(self) -> None:
        self.children: typing.Dict[str, TreeNode] = dict()
        self.data: typing.List[Profile.ProjectReference] = list()


class TreeModel(Observable.Observable):

    def __init__(self, profile: Profile.Profile) -> None:
        super().__init__()

        # cache
        self.__project_panel_items: typing.Optional[typing.List[ProjectPanelItemLike]] = None

        # define the top level list
        self.__root_node = TreeNode()

        # define events to make this a model
        self.property_changed_event = Event.Event()

        # define the closed items
        self.__closed_items = set(profile.closed_items)
        self.on_closed_items_changed: typing.Optional[typing.Callable[[typing.Set[str]], None]] = None

        def update_items(item: Observer.ItemValue) -> None:
            if self.__project_panel_items is not None:
                self.property_changed_event.fire("value")

        # build an observer that will call update_items whenever any of the project_references changes.
        oo = Observer.ObserverBuilder()
        oo.source(profile).tuple(
            oo.x.ordered_sequence_from_array("project_references").collect_list()).action_fn(update_items)

        self.__profile_observer = typing.cast(Observer.AbstractItemSource, oo.make_observable())

    def close(self) -> None:
        self.__profile_observer.close()
        self.__profile_observer = typing.cast(typing.Any, None)
        self.__project_panel_items = None

    def update_project_references(self, project_references: typing.Sequence[Profile.ProjectReference]) -> None:
        # build hierarchy of nodes reflecting the project reference parts (strings).
        # this is called when the projects model changes.
        self.__project_panel_items = None
        root_node = TreeNode()
        for project_reference in project_references:
            parts = project_reference.project_reference_parts
            node = root_node
            for part in parts[:-1]:
                node = node.children.setdefault(part, TreeNode())
            node.data.append(project_reference)
        self.__root_node = root_node
        self.property_changed_event.fire("value")

    # recursively construct the project panel items
    def __construct_project_panel_items(self, key_path: typing.Sequence[str], node: TreeNode, closed: bool, project_panel_items: typing.List[ProjectPanelItemLike], closed_items: typing.Set[str], encountered_items: typing.Set[str]) -> None:
        # if the node has no data (no projects) and no children, do not display it; move down a level.
        key_path_list = list(key_path)
        if len(node.data) == 0 and len(node.children) == 1:
            # this node represents a directory that only has a sub directory.
            # start by extracting the key and only child.
            key, child = list(node.children.items())[0]
            # if not root (the key path is not empty), combine the child with the key (directory path).
            if len(key_path_list) > 0:
                new_key = key_path_list[:-1] + [key_path_list[-1] + (key if key_path_list[-1].endswith("/") else "/" + key)]
            # otherwise combine the child with the key (directory path).
            else:
                new_key = [key]
            # recurse
            self.__construct_project_panel_items(new_key, child, closed, project_panel_items, closed_items, encountered_items)
        else:
            # this node represents a directory that more than one of either sub directory or project.
            folder_key = "/".join(key_path_list)
            folder_closed = folder_key in self.__closed_items or closed
            if len(key_path_list) > 0:
                encountered_items.add(folder_key)
                if not closed:  # closed indicates whether the parent is closed
                    project_panel_items.append(ProjectPanelFolderItem(node, len(key_path_list) - 1, key_path_list[-1], folder_closed, folder_key))
            for key, child in node.children.items():
                self.__construct_project_panel_items(key_path_list + [key], child, folder_closed, project_panel_items, closed_items, encountered_items)
            for project_reference in typing.cast(typing.Sequence[Profile.ProjectReference], node.data):
                project_reference_parts = project_reference.project_reference_parts
                project_key = "/".join(key_path_list + [project_reference_parts[-1]]) if project_reference_parts else str(id(project_reference))
                encountered_items.add(project_key)
                if not folder_closed:

                    def handle_item_controller_title_changed(t: str) -> None:
                        self.property_changed_event.fire("value")

                    display_item_counter = ProjectCounterDisplayItem(project_reference)
                    display_item_counter.on_title_changed = handle_item_controller_title_changed
                    project_panel_items.append(ProjectPanelProjectItem(len(key_path_list), project_reference, display_item_counter))

    @property
    def value(self) -> typing.Sequence[ProjectPanelItemLike]:
        # build the value reflecting a compact version of the node hierarchy.
        # nodes with only one child are combined with that child.
        # building the project panel is expensive; so cache it.

        if not self.__project_panel_items:
            project_panel_items: typing.List[ProjectPanelItemLike] = list()
            encountered_items: typing.Set[str] = set()
            self.__construct_project_panel_items(list(), self.__root_node, False, project_panel_items, self.__closed_items, encountered_items)
            self.__closed_items = self.__closed_items.intersection(encountered_items)
            self.__project_panel_items = project_panel_items

        return self.__project_panel_items

    def toggle_folder(self, folder_key: str) -> None:
        if not folder_key in self.__closed_items:
            self.__closed_items.add(folder_key)
        else:
            self.__closed_items.remove(folder_key)
        self.__project_panel_items = None
        self.property_changed_event.fire("value")
        if self.on_closed_items_changed:
            self.on_closed_items_changed(self.__closed_items)


class ProjectTreeCanvasItemDelegate(Widgets.ListCanvasItemDelegate):

    def __init__(self, window: Window.Window, tree_model: TreeModel) -> None:
        super().__init__()
        self.__window = window
        self.__tree_model = tree_model
        get_font_metrics_fn = self.__window.ui.get_font_metrics
        self.__folder_indent = typing.cast(int, get_font_metrics_fn("12px", "\N{BLACK DOWN-POINTING TRIANGLE} ").width)
        self.__project_indent = typing.cast(int, get_font_metrics_fn("12px", "\N{OPEN FILE FOLDER} ").width)

    def mouse_pressed_in_item(self, mouse_index: int, pos: Geometry.IntPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        display_item = self.__tree_model.value[mouse_index]
        indent = self.__calculate_indent(display_item.indent, 0)
        if display_item.is_folder and indent < pos.x < indent + self.__folder_indent:
            self.__tree_model.toggle_folder(display_item.folder_key)
            return True
        return False

    def paint_item(self, drawing_context: DrawingContext.DrawingContext, display_item: typing.Any, rect: Geometry.IntRect, is_selected: bool) -> None:
        item_string = str(display_item)
        with drawing_context.saver():
            drawing_context.fill_style = "#000"
            drawing_context.font = "12px bold" if display_item.is_enabled else "12px"
            drawing_context.text_align = 'left'
            drawing_context.text_baseline = 'bottom'
            # drawing_context.fill_text("\N{BALLOT BOX}", rect[0][1] + 4, rect[0][0] + 20 - 4)
            extra_indent = self.__project_indent if not display_item.is_folder else 0
            drawing_context.fill_text(item_string, rect.left + self.__calculate_indent(display_item.indent, extra_indent), rect.top + 20 - 4)

    def item_tool_tip(self, index: int) -> typing.Optional[str]:
        display_item = self.__tree_model.value[index]
        if isinstance(display_item, ProjectPanelProjectItem):
            return display_item.project_reference.project.storage_location_str if display_item.project_reference.project else _("Missing")
        return None

    def context_menu_event(self, index: typing.Optional[int], x: int, y: int, gx: int, gy: int) -> bool:
        if index is not None:
            display_item = self.__tree_model.value[index]
            menu = self.__window.ui.create_context_menu(typing.cast(UserInterface.Window, self.__window))  # TODO: why is this cast required? something is ill-defined.
            if isinstance(display_item, ProjectPanelProjectItem) and display_item.project_reference.project:
                menu.add_menu_item(_(f"Open Project Location"), functools.partial(reveal_project, display_item.project_reference))
            elif isinstance(display_item, ProjectPanelFolderItem):
                menu.add_menu_item(_(f"Open Folder Location"), functools.partial(open_location, pathlib.Path(display_item.folder_key)))
            menu.popup(gx, gy)
            return True
        return False

    def __calculate_indent(self, display_item_indent: int, extra_indent: int) -> int:
        return display_item_indent * self.__folder_indent + extra_indent


class ProjectTreeWidget(Widgets.CompositeWidgetBase):

    def __init__(self, window: Window.Window, profile: Profile.Profile):
        content_widget = window.ui.create_column_widget()
        super().__init__(content_widget)

        ui = window.ui

        self._tree_model = TreeModel(profile)

        def closed_items_changed(closed_items: typing.Set[str]) -> None:
            profile.closed_items = list(closed_items)

        self._tree_model.on_closed_items_changed = closed_items_changed

        self._tree_selection = Selection.IndexedSelection(Selection.Style.multiple)

        projects_list_widget = Widgets.ListWidget(ui, ProjectTreeCanvasItemDelegate(window, self._tree_model), selection=self._tree_selection, v_scroll_enabled=False, v_auto_resize=True)
        projects_list_widget.wants_drag_events = True
        projects_list_widget.bind_items(Binding.PropertyBinding(self._tree_model, "value"))

        projects_section = Widgets.SectionWidget(ui, _("Projects"), projects_list_widget)
        projects_section.expanded = True

        content_widget.add(projects_section)

        # configure an observer for watching for project references changes.
        # this serves as the master updater for changes. move to document controller?

        def project_references_changed(item: Observer.ItemValue) -> None:
            # update the tree model.
            project_references = typing.cast(typing.Sequence[Profile.ProjectReference], item)
            self._tree_model.update_project_references(project_references)

        oo = Observer.ObserverBuilder()
        oo.source(profile).ordered_sequence_from_array("project_references").collect_list().action_fn(project_references_changed)
        self.__projects_model_observer = typing.cast(Observer.AbstractItemSource, oo.make_observable())

    def close(self) -> None:
        self._tree_model.on_closed_items_changed = None
        self.__projects_model_observer.close()
        self.__projects_model_observer = typing.cast(typing.Any, None)
        super().close()


class CollectionListCanvasItemDelegate(Widgets.ListCanvasItemDelegate):

    def __init__(self, collection_selection: Selection.IndexedSelection):
        super().__init__()
        self.__collection_selection = collection_selection

    def close(self) -> None:
        pass

    def paint_item(self, drawing_context: DrawingContext.DrawingContext, display_item: typing.Any, rect: Geometry.IntRect, is_selected: bool) -> None:
        is_smart_collection = display_item.is_smart_collection if display_item else False
        title = ("\N{LEDGER} " if is_smart_collection else "\N{NOTEBOOK} ") + (display_item.title if display_item else str())

        with drawing_context.saver():
            drawing_context.fill_style = "#000"
            drawing_context.font = "12px italic" if is_smart_collection else "12px"
            drawing_context.text_align = 'left'
            drawing_context.text_baseline = 'bottom'
            drawing_context.fill_text(title, rect[0][1] + 4, rect[0][0] + 20 - 4)

    def item_can_drop_mime_data(self, mime_data: UserInterface.MimeData, action: str, drop_index: int) -> bool:
        list_display_item = self.items[drop_index]
        is_smart_collection = list_display_item.is_smart_collection if list_display_item else False
        display_items = MimeTypes.mime_data_get_display_items(mime_data, list_display_item.document_model)
        if list_display_item and not is_smart_collection and display_items:
            # if the display item exists in this document, then it is copied to the
            # target group. if it doesn't exist in this document, then it is coming
            # from another document and can't be handled here.
            return True
        return False

    def item_drop_mime_data(self, mime_data: UserInterface.MimeData, action: str, drop_index: int) -> str:
        list_display_item = self.items[drop_index]
        is_smart_collection = list_display_item.is_smart_collection if list_display_item else False
        display_items = MimeTypes.mime_data_get_display_items(mime_data, list_display_item.document_model)
        if list_display_item and not is_smart_collection and display_items:
            # if the display item exists in this document, then it is copied to the
            # target group. if it doesn't exist in this document, then it is coming
            # from another document and can't be handled here.
            document_controller = list_display_item.document_controller
            data_group = list_display_item.data_group
            command = document_controller.create_insert_data_group_display_items_command(data_group, len(data_group.display_items), display_items)
            command.perform()
            document_controller.push_undo_command(command)
            return "copy"
        return "ignore"

    def delete_pressed(self) -> None:
        index = self.__collection_selection.current_index
        list_display_item = self.items[index] if index is not None else None
        data_group = list_display_item.data_group
        if data_group:
            list_display_item.document_controller.remove_data_group_from_container(data_group, list_display_item.document_controller.document_model._project)


class CollectionsWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui: UserInterface.UserInterface, document_controller: DocumentController.DocumentController) -> None:
        content_widget = ui.create_column_widget()
        super().__init__(content_widget)

        document_model = document_controller.document_model

        all_items_controller = CollectionDisplayItemCounter(_("All"), None, "all", document_controller)
        persistent_items_controller = CollectionDisplayItemCounter(_("Persistent"), None, "persistent", document_controller)
        live_items_controller = CollectionDisplayItemCounter(_("Live"), None, "temporary", document_controller)
        latest_items_controller = CollectionDisplayItemCounter(_("Latest Session"), None, "latest-session", document_controller)

        self.__item_controllers = [
            all_items_controller,
            persistent_items_controller,
            live_items_controller,
            latest_items_controller
        ]

        self.__data_group_controllers: typing.List[CollectionDisplayItemCounter] = list()

        collection_selection = Selection.IndexedSelection(Selection.Style.single_or_none)

        collections_list_widget = Widgets.ListWidget(ui, CollectionListCanvasItemDelegate(collection_selection), selection=collection_selection, v_scroll_enabled=False, v_auto_resize=True)
        collections_list_widget.wants_drag_events = True

        def filter_changed(data_group: typing.Optional[DataGroup.DataGroup], filter_id: typing.Optional[str]) -> None:
            if data_group:
                for index, controller in enumerate(collections_list_widget.items):
                    if data_group == controller.data_group:
                        collection_selection.set(index)
                        break
            else:
                if filter_id == "latest-session":
                    collection_selection.set(3)
                elif filter_id == "temporary":
                    collection_selection.set(2)
                elif filter_id == "persistent":
                    collection_selection.set(1)
                else:
                    collection_selection.set(0)

        self.__filter_changed_event_listener = document_controller.filter_changed_event.listen(filter_changed)

        def collections_changed(t: str) -> None:
            collections_list_widget.items = [
                all_items_controller,
                persistent_items_controller,
                live_items_controller,
                latest_items_controller,
            ] + self.__data_group_controllers

        all_items_controller.on_title_changed = collections_changed
        persistent_items_controller.on_title_changed = collections_changed
        live_items_controller.on_title_changed = collections_changed
        latest_items_controller.on_title_changed = collections_changed

        def document_model_item_inserted(key: str, value: typing.Any, before_index: int) -> None:
            if key == "data_groups":
                data_group = value
                controller = CollectionDisplayItemCounter(data_group.title, data_group, None, document_controller)
                self.__data_group_controllers.insert(before_index, controller)
                controller.on_title_changed = collections_changed
                collections_changed(str())

        def document_model_item_removed(key: str, value: typing.Any, index: int) -> None:
            if key == "data_groups":
                controller = self.__data_group_controllers.pop(index)
                controller.close()
                collections_changed(str())

        self.__document_model_item_inserted_listener = document_model.item_inserted_event.listen(document_model_item_inserted)
        self.__document_model_item_removed_listener = document_model.item_removed_event.listen(document_model_item_removed)

        data_group, filter_id = document_controller.get_data_group_and_filter_id()
        filter_changed(data_group, filter_id)

        for index, data_group in enumerate(document_model.data_groups):
            document_model_item_inserted("data_groups", data_group, index)

        collections_changed(str())

        def collections_selection_changed(indexes: typing.AbstractSet[int]) -> None:
            if len(indexes) == 0:
                controller = collections_list_widget.items[0]
                document_controller.set_filter(controller.filter_id)
            elif len(indexes) == 1:
                controller = collections_list_widget.items[list(indexes)[0]]
                if controller.is_smart_collection:
                    document_controller.set_filter(controller.filter_id)
                    document_controller.set_data_group(None)
                else:
                    document_controller.set_filter(None)
                    document_controller.set_data_group(controller.data_group)

        collections_list_widget.on_selection_changed = collections_selection_changed

        collections_column = ui.create_column_widget()
        collections_column.add(collections_list_widget)

        collections_section = Widgets.SectionWidget(ui, _("Collections"), collections_column)
        collections_section.expanded = True

        content_widget.add(collections_section)
        content_widget.add_stretch()

        # for testing
        self._collection_selection = collection_selection

    def close(self) -> None:
        for controller in self.__data_group_controllers:
            controller.close()
        self.__data_group_controllers.clear()
        for item_controller in self.__item_controllers:
            item_controller.close()
        self.__item_controllers.clear()
        self.__filter_changed_event_listener.close()
        self.__filter_changed_event_listener = typing.cast(typing.Any, None)
        self.__document_model_item_inserted_listener.close()
        self.__document_model_item_inserted_listener = typing.cast(typing.Any, None)
        self.__document_model_item_removed_listener.close()
        self.__document_model_item_removed_listener = typing.cast(typing.Any, None)
        super().close()


class CollectionsPanel(Panel.Panel):

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, _("Collections"))

        ui = document_controller.ui

        self._collections_section = CollectionsWidget(ui, document_controller)

        column = ui.create_column_widget()
        column.add(self._collections_section)
        column.add_stretch()

        scroll_area = ui.create_scroll_area_widget(properties=properties)
        scroll_area.set_scrollbar_policies("off", "needed")
        scroll_area.content = column

        self.widget = scroll_area

    @property
    def _collection_selection(self) -> Selection.IndexedSelection:
        return self._collections_section._collection_selection


class ProjectDialog(Dialog.ActionDialog):

    def __init__(self, ui: UserInterface.UserInterface, app: Application.Application) -> None:
        super().__init__(ui, _("Project Manager"), app=app, window_style="window", persistent_id="ProjectsDialog")

        projects_section = ProjectTreeWidget(self, app.profile)

        column = ui.create_column_widget()
        column.add(projects_section)
        column.add_stretch()

        scroll_area = ui.create_scroll_area_widget()
        scroll_area.set_scrollbar_policies("off", "needed")
        scroll_area.content = column

        column = self.content
        column.add_spacing(6)
        column.add(scroll_area)
