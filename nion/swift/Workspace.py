from __future__ import annotations

# standard libraries
import copy
import functools
import gettext
import random
import string
import threading
import time
import typing
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DisplayPanel
from nion.swift import FilterPanel
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift import Undo
from nion.swift.model import Persistence
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.ui import CanvasItem
from nion.ui import UserInterface

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import DisplayItem
    from nion.swift.model import DocumentModel
    from nion.swift.model import Project


_ = gettext.gettext


def create_image_desc() -> Persistence.PersistentDictType:
    return {"type": "image", "identifier": "".join([random.choice(string.ascii_uppercase) for _ in range(2)]), "uuid": str(uuid.uuid4())}


def create_splitter_desc(orientation: str, splits: typing.Sequence[float], children: typing.Sequence[Persistence.PersistentDictType]) -> Persistence.PersistentDictType:
    return {"type": "splitter", "orientation": orientation, "splits": list(splits), "children": list(children)}


class CreateWorkspaceCommand(Undo.UndoableCommand):
    def __init__(self, workspace_controller: Workspace, name: str) -> None:
        super().__init__("Create Workspace")
        self.__workspace_controller = workspace_controller
        self.__workspace_layout_uuid = workspace_controller._workspace.uuid
        self.__new_name = name
        self.__new_layout: typing.Optional[Persistence.PersistentDictType] = None
        self.__new_workspace_id: typing.Optional[str] = None
        self.initialize()

    def _get_modified_state(self) -> typing.Any:
        return self.__workspace_controller._project.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        self.__workspace_controller._project.modified_state = modified_state

    def perform(self) -> None:
        new_workspace = self.__workspace_controller.new_workspace(name=self.__new_name, layout=self.__new_layout, workspace_id=self.__new_workspace_id)
        self.__workspace_controller._change_workspace(new_workspace)

    def _undo(self) -> None:
        new_workspace = self.__workspace_controller._workspace
        workspace_layout = self.__workspace_controller.get_workspace_layout_by_uuid(self.__workspace_layout_uuid)
        assert workspace_layout
        self.__new_layout = self.__workspace_controller._workspace.layout
        self.__new_workspace_id = self.__workspace_controller._workspace.workspace_id
        self.__workspace_controller._change_workspace(workspace_layout)
        self.__workspace_controller._project.remove_item("workspaces", new_workspace)

    def _redo(self) -> None:
        self.perform()


class RemoveWorkspaceCommand(Undo.UndoableCommand):
    def __init__(self, workspace_controller: Workspace):
        super().__init__("Remove Workspace")
        self.__workspace_controller = workspace_controller
        self.__old_name = workspace_controller._workspace.name
        self.__old_layout = workspace_controller._workspace.layout
        self.__old_workspace_id = workspace_controller._workspace.workspace_id
        self.__old_workspace_index = workspace_controller._project.workspaces.index(workspace_controller._workspace)
        self.initialize()

    def _get_modified_state(self) -> typing.Any:
        return self.__workspace_controller._project.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        self.__workspace_controller._project.modified_state = modified_state

    def perform(self) -> None:
        assert len(self.__workspace_controller._project.workspaces) > 1
        old_workspace = self.__workspace_controller._workspace
        self.__workspace_controller.change_to_previous_workspace()
        self.__workspace_controller._project.remove_item("workspaces", old_workspace)

    def _undo(self) -> None:
        new_workspace = self.__workspace_controller.new_workspace(name=self.__old_name, layout=self.__old_layout, workspace_id=self.__old_workspace_id, index=self.__old_workspace_index)
        self.__workspace_controller._change_workspace(new_workspace)

    def _redo(self) -> None:
        self.perform()


class RenameWorkspaceCommand(Undo.UndoableCommand):
    def __init__(self, workspace_controller: Workspace, name: str):
        super().__init__("Rename Workspace")
        self.__workspace_controller = workspace_controller
        self.__old_name = workspace_controller._workspace.name
        self.__new_name = name
        self.initialize()

    def _get_modified_state(self) -> typing.Any:
        return self.__workspace_controller._project.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        self.__workspace_controller._project.modified_state = modified_state

    def perform(self) -> None:
        self.__workspace_controller._workspace.name = self.__new_name

    def _undo(self) -> None:
        self.__workspace_controller._workspace.name = self.__old_name

    def _redo(self) -> None:
        self.perform()


class CloneWorkspaceCommand(Undo.UndoableCommand):
    def __init__(self, workspace_controller: Workspace, name: str):
        super().__init__("Clone Workspace")
        self.__workspace_controller = workspace_controller
        self.__workspace_layout_uuid = workspace_controller._workspace.uuid
        self.__new_name = name
        self.__new_layout = workspace_controller._workspace.layout
        self.__new_workspace_id: typing.Optional[str] = None
        self.initialize()

    def _get_modified_state(self) -> typing.Any:
        return self.__workspace_controller._project.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        self.__workspace_controller._project.modified_state = modified_state

    def perform(self) -> None:
        new_workspace = self.__workspace_controller.new_workspace(name=self.__new_name, layout=self.__new_layout, workspace_id=self.__new_workspace_id)
        self.__workspace_controller._change_workspace(new_workspace)

    def _undo(self) -> None:
        new_workspace = self.__workspace_controller._workspace
        workspace_layout = self.__workspace_controller.get_workspace_layout_by_uuid(self.__workspace_layout_uuid)
        assert workspace_layout
        self.__new_layout = self.__workspace_controller._workspace.layout
        self.__new_workspace_id = self.__workspace_controller._workspace.workspace_id
        self.__workspace_controller._change_workspace(workspace_layout)
        self.__workspace_controller._project.remove_item("workspaces", new_workspace)

    def _redo(self) -> None:
        self.perform()


class ChangeWorkspaceContentsCommand(Undo.UndoableCommand):
    def __init__(self, workspace_controller: Workspace, title: str, old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None):
        super().__init__(title)
        self.__workspace_controller = workspace_controller
        self.__old_workspace_layout = old_workspace_layout if old_workspace_layout else workspace_controller.deconstruct()
        self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
        self.initialize()

    @property
    def _old_workspace_layout(self) -> typing.Optional[Persistence.PersistentDictType]:
        return self.__old_workspace_layout

    def _get_modified_state(self) -> typing.Any:
        return self.__workspace_controller._project.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        self.__workspace_controller._project.modified_state = modified_state

    def _undo(self) -> None:
        self.__new_workspace_layout = self.__workspace_controller.deconstruct()
        self.__workspace_controller.reconstruct(self.__old_workspace_layout)

    def _redo(self) -> None:
        assert self.__new_workspace_layout is not None
        self.__workspace_controller.reconstruct(self.__new_workspace_layout)


class Workspace:
    """
        The Workspace object keeps the overall layout of the window. It contains
        root item which contains tab groups arranged into boxes (rows and columns).
        The boxes contain other boxes or tab groups. Tab groups contain tabs which contain
        a single panel.

        The Workspace is able to save/restore itself from a text stream. It is also able to
        record changes to the workspace from the enclosing application. When restoring its
        layout, it is able to handle cases where the size/shape of the window is different
        from its original size/shape when saved.
    """

    def __init__(self, document_controller: DocumentController.DocumentController, workspace_id: str):
        self.__document_controller_weakref = weakref.ref(document_controller)

        self.ui = document_controller.ui

        self.workspace_manager = WorkspaceManager()

        self.workspace_id = workspace_id

        self.dock_panels: typing.List[Panel.Panel] = []
        self.display_panels: typing.List[DisplayPanel.DisplayPanel] = []

        self.__canvas_item = typing.cast(CanvasItem.CanvasItemComposition, None)

        # create the root element
        root_widget = self.ui.create_column_widget(properties={"min-width": 640, "min-height": 480})
        self.__content_column = self.ui.create_column_widget()
        self.message_column = self.ui.create_column_widget()
        self.filter_panel = self.workspace_manager.create_filter_panel(document_controller)
        self.filter_row = self.filter_panel.widget
        self.image_row = self.ui.create_column_widget()
        self.__content_column.add(self.message_column)
        self.__content_column.add(self.filter_row)
        self.__content_column.add(self.image_row, fill=True)
        self.filter_row.visible = False
        root_widget.add(self.__content_column)

        self.__message_boxes: typing.Dict[str, UserInterface.BoxWidget] = dict()

        # configure the document window (central widget)
        document_controller.attach_widget(root_widget)

        visible_panels = []
        if self.workspace_id == "library":
            visible_panels = ["toolbar-panel", "data-panel", "histogram-panel", "info-panel", "inspector-panel"]

        self.create_panels(visible_panels)

        self.__workspace: typing.Optional[WorkspaceLayout.WorkspaceLayout] = None
        self.__change_splitter_command: typing.Optional[Undo.UndoableCommand] = None
        self.__change_splitter_splits: typing.List[float] = list()

    def close(self) -> None:
        for message_box_widget in copy.copy(list(self.__message_boxes.values())):
            self.message_column.remove(message_box_widget)
        self.__message_boxes.clear()
        if self.__workspace:
            self.__sync_layout()
        self.display_panels = []
        self.__canvas_item = typing.cast(CanvasItem.CanvasItemComposition, None)
        self.__workspace = None
        for dock_panel in self.dock_panels:
            dock_panel.close()
        self.__content_column = typing.cast(typing.Any, None)
        self.filter_row = typing.cast(typing.Any, None)
        self.image_row = typing.cast(typing.Any, None)
        self.document_controller.detach_widget()

    @property
    def dock_widgets(self) -> typing.List[UserInterface.DockWidget]:
        if self.dock_panels:
            return list(dock_panel.dock_widget for dock_panel in self.dock_panels)
        return list()

    def periodic(self) -> None:
        for dock_panel in self.dock_panels:
            dock_panel.periodic()

    def restore_geometry_state(self) -> typing.Tuple[str, str]:
        geometry = self.ui.get_persistent_string("Workspace/%s/Geometry" % self.workspace_id)
        state = self.ui.get_persistent_string("Workspace/%s/State" % self.workspace_id)
        return geometry, state

    def save_geometry_state(self, geometry: str, state: str) -> None:
        # ugh. this has the side effect of saving the layout when the geometry state is saved.
        self.__sync_layout()
        self.ui.set_persistent_string("Workspace/%s/Geometry" % self.workspace_id, geometry)
        self.ui.set_persistent_string("Workspace/%s/State" % self.workspace_id, state)

    @property
    def document_controller(self) -> DocumentController.DocumentController:
        document_controller = self.__document_controller_weakref()
        assert document_controller
        return document_controller

    @property
    def document_model(self) -> DocumentModel.DocumentModel:
        assert self.document_controller
        return self.document_controller.document_model

    @property
    def _project(self) -> Project.Project:
        return self.document_controller.project

    @property
    def _canvas_item(self) -> CanvasItem.CanvasItemComposition:
        return self.__canvas_item

    def _find_dock_panel(self, dock_panel_id: str) -> typing.Optional[Panel.Panel]:
        for dock_panel in self.dock_panels:
            if dock_panel.panel_id == dock_panel_id:
                return dock_panel
        return None

    def create_panels(self, visible_panels: typing.Optional[typing.List[str]] = None) -> None:
        # get the document controller
        document_controller = self.document_controller

        # add registered panels
        for panel_id in self.workspace_manager.panel_ids:
            title, positions, position, properties = self.workspace_manager.get_panel_info(panel_id)
            if position != "central":
                dock_panel = self.create_panel(document_controller, panel_id, title, positions, position, properties)
                if dock_panel:  # could have failed to create due to exception
                    if visible_panels is None or panel_id in visible_panels:
                        dock_panel.show()
                    else:
                        dock_panel.hide()

    def create_panel(self, document_controller: DocumentController.DocumentController, panel_id: str, title: str,
                     positions: typing.Sequence[str], position: str,
                     properties: typing.Optional[Persistence.PersistentDictType]) -> typing.Optional[Panel.Panel]:
        try:
            panel = self.workspace_manager.create_panel_content(document_controller, panel_id, title, positions, position, properties)
            assert panel is not None, "panel is None [%s]" % panel_id
            assert panel.widget is not None, "panel widget is None [%s]" % panel_id
            self.dock_panels.append(panel)
            return panel
        except Exception as e:
            import traceback
            print("Exception creating panel '" + panel_id + "': " + str(e))
            traceback.print_exc()
            traceback.print_stack()
            return None

    def display_display_item_in_display_panel(self, display_item: DisplayItem.DisplayItem, display_panel_id: str) -> None:
        for display_panel in self.display_panels:
            if display_panel.display_panel_id == display_panel_id:
                display_panel.set_display_panel_display_item(display_item)
                self.__sync_layout()

    def _construct(self, desc: Persistence.PersistentDictType, display_panels: typing.List[DisplayPanel.DisplayPanel]) -> typing.Tuple[typing.Optional[CanvasItem.AbstractCanvasItem], typing.Optional[DisplayPanel.DisplayPanel]]:
        selected_display_panel = None
        type = desc["type"]
        container = None
        item = None
        def _post_children_adjust() -> None: pass
        post_children_adjust = _post_children_adjust
        if type == "splitter":
            splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation=desc.get("orientation"))
            splitter_canvas_item.on_splits_will_change = functools.partial(self._splits_will_change, splitter_canvas_item)
            splitter_canvas_item.on_splits_changed = functools.partial(self._splits_did_change, splitter_canvas_item)
            def splitter_post_children_adjust() -> None:
                splits = desc.get("splits")
                if splits is not None:
                    splitter_canvas_item.splits = splits
            post_children_adjust = splitter_post_children_adjust
            container = splitter_canvas_item
        elif type == "image":
            display_panel = DisplayPanel.DisplayPanel(self.document_controller, desc)
            display_panel.on_contents_changed = self.__sync_layout
            display_panels.append(display_panel)
            if desc.get("selected", False):
                selected_display_panel = display_panel
            item = display_panel
        if container:
            children = desc.get("children", list())
            for child_desc in children:
                child_canvas_item, child_selected_display_panel = self._construct(child_desc, display_panels)
                if child_canvas_item:
                    container.add_canvas_item(child_canvas_item)
                selected_display_panel = child_selected_display_panel if child_selected_display_panel else selected_display_panel
            post_children_adjust()
            return container, selected_display_panel
        return item, selected_display_panel

    def deconstruct(self) -> Persistence.PersistentDictType:
        return self._deconstruct(self.__canvas_item.canvas_items[0])

    def reconstruct(self, d: Persistence.PersistentDictType) -> None:
        display_panels: typing.List[DisplayPanel.DisplayPanel] = list()
        selected_display_panel = self._reconstruct(d, self.__canvas_item, self.__canvas_item.canvas_items[0], display_panels)
        self.display_panels = display_panels
        self.document_controller.selected_display_panel = selected_display_panel

    def _reconstruct(self, d: Persistence.PersistentDictType, container: CanvasItem.CanvasItemComposition, canvas_item: CanvasItem.AbstractCanvasItem, display_panels: typing.List[DisplayPanel.DisplayPanel]) -> typing.Optional[DisplayPanel.DisplayPanel]:
        selected_display_panel = None
        type = d["type"]
        if type == "splitter":
            if isinstance(canvas_item, CanvasItem.SplitterCanvasItem) and canvas_item.orientation == d.get("orientation", None):
                canvas_item_container = canvas_item
                children = d.get("children", list())
                if len(children) == len(canvas_item_container.canvas_items):
                    for child_desc, child_canvas_item in zip(children, canvas_item_container.canvas_items):
                        child_selected_display_panel = self._reconstruct(child_desc, canvas_item_container,
                                                                         child_canvas_item, display_panels)
                        selected_display_panel = child_selected_display_panel if child_selected_display_panel else selected_display_panel
                    splits = d.get("splits")
                    if splits is not None:
                        canvas_item_container.splits = splits
                    return selected_display_panel
            # fall through
            new_canvas_item, selected_display_panel = self._construct(d, display_panels)
            if new_canvas_item:
                container.replace_canvas_item(canvas_item, new_canvas_item)
            return selected_display_panel
        elif type == "image":
            if isinstance(canvas_item, DisplayPanel.DisplayPanel):
                display_panel = canvas_item
                display_panels.append(display_panel)
                display_panel.change_display_panel_content(d)
                if d.get("selected", False):
                    selected_display_panel = display_panel
                return selected_display_panel
            # fall through
            new_canvas_item, selected_display_panel = self._construct(d, display_panels)
            if new_canvas_item:
                container.replace_canvas_item(canvas_item, new_canvas_item)
            return selected_display_panel
        return selected_display_panel

    def __get_display_panel_by_canvas_item(self, canvas_item: CanvasItem.AbstractCanvasItem) -> typing.Optional[DisplayPanel.DisplayPanel]:
        for display_panel in self.display_panels:
            if display_panel == canvas_item:
                return display_panel
        return None

    def get_display_panel_by_uuid(self, display_panel_uuid: uuid.UUID) -> typing.Optional[DisplayPanel.DisplayPanel]:
        for display_panel in self.display_panels:
            if display_panel.uuid == display_panel_uuid:
                return display_panel
        return None

    def _deconstruct(self, canvas_item: CanvasItem.AbstractCanvasItem) -> Persistence.PersistentDictType:
        if isinstance(canvas_item, CanvasItem.SplitterCanvasItem):
            children = [self._deconstruct(child_canvas_item) for child_canvas_item in canvas_item.canvas_items]
            d = create_splitter_desc(canvas_item.orientation, canvas_item.splits, children)
            return d
        if isinstance(canvas_item, DisplayPanel.DisplayPanel):
            display_panel = canvas_item
            d = create_image_desc()
            if display_panel._is_selected():
                d["selected"] = True
            d.update(display_panel.save_contents())
            return d
        return dict()

    @property
    def _workspace(self) -> WorkspaceLayout.WorkspaceLayout:
        assert self.__workspace
        return self.__workspace

    @property
    def _workspace_layout(self) -> Persistence.PersistentDictType:
        return self.deconstruct()

    def close_display_panels(self, display_panels: typing.Sequence[DisplayPanel.DisplayPanel]) -> None:
        command = ChangeWorkspaceContentsCommand(self, _("Close Display Panel"))
        for display_panel in display_panels:
            if len(self.display_panels) > 1:
                self._remove_display_panel(display_panel, None)
        self.document_controller.push_undo_command(command)

    def clear_display_panels(self, display_panels: typing.Sequence[DisplayPanel.DisplayPanel]) -> None:
        command = ChangeWorkspaceContentsCommand(self, _("Clear Display Panel Contents"))
        d = {"type": "image", "display-panel-type": "empty-display-panel"}
        for display_panel in display_panels:
            display_panel.change_display_panel_content(d)
        self.document_controller.push_undo_command(command)

    def select_sibling_display_panels(self, display_panels: typing.Sequence[DisplayPanel.DisplayPanel]) -> None:
        select_display_panels = list(display_panels)

        def append_child_display_panels(splitter_canvas_item: CanvasItem.SplitterCanvasItem,
                                        display_panels: typing.List[DisplayPanel.DisplayPanel]) -> None:
            for canvas_item in splitter_canvas_item.canvas_items:
                if isinstance(canvas_item, DisplayPanel.DisplayPanel):
                    if canvas_item not in display_panels:
                        display_panels.append(canvas_item)
                elif isinstance(canvas_item, CanvasItem.SplitterCanvasItem):
                    append_child_display_panels(canvas_item, display_panels)

        def get_ancestor_splitter(display_panel: DisplayPanel.DisplayPanel, display_panels: typing.Sequence[DisplayPanel.DisplayPanel]) -> typing.Optional[CanvasItem.SplitterCanvasItem]:
            container = display_panel.container
            while isinstance(container, CanvasItem.SplitterCanvasItem):
                descendant_display_panels: typing.List[DisplayPanel.DisplayPanel] = list()
                append_child_display_panels(container, descendant_display_panels)
                # check if all descendants are in the initial set of display panels
                if set(descendant_display_panels) - set(display_panels):
                    # not all descendant are selected
                    return container
                container = container.container
            return None

        for display_panel in display_panels:
            splitter_canvas_item = get_ancestor_splitter(display_panel, display_panels)
            if splitter_canvas_item:
                append_child_display_panels(splitter_canvas_item, select_display_panels)

        for display_panel in select_display_panels:
            if display_panel != self.document_controller.selected_display_panel:
                self.document_controller.add_secondary_display_panel(display_panel)

    def switch_to_display_content(self, display_panel: DisplayPanel.DisplayPanel, display_panel_type: str, display_item: typing.Optional[DisplayItem.DisplayItem] = None) -> None:
        d: Persistence.PersistentDictType = {"type": "image", "display-panel-type": display_panel_type}
        if display_item and display_panel_type != "empty-display-panel":
            d["display_item_specifier"] = Persistence.write_persistent_specifier(display_item.uuid)
        command = ChangeWorkspaceContentsCommand(self, _("Replace Display Panel"))
        display_panel.change_display_panel_content(d)
        self.document_controller.push_undo_command(command)

    def change_workspace(self, workspace_layout: WorkspaceLayout.WorkspaceLayout) -> None:
        command = ChangeWorkspaceContentsCommand(self, _("Change Workspace"))
        self._change_workspace(workspace_layout)
        self.document_controller.push_undo_command(command)

    def _change_workspace(self, workspace_layout: WorkspaceLayout.WorkspaceLayout) -> None:
        assert workspace_layout is not None
        # save the current workspace
        if self.__workspace:
            self.__sync_layout()
            self.__workspace = None
        # remove existing layout and canvas item
        self.display_panels = []
        for child in copy.copy(self.image_row.children):
            self.image_row.remove(child)
        # create new layout and canvas item
        self.__canvas_item = CanvasItem.CanvasItemComposition()
        canvas_widget = self.ui.create_canvas_widget(layout_render=CanvasItem.RootLayoutRender)
        canvas_widget.canvas_item.add_canvas_item(self.__canvas_item)
        self._canvas_widget = canvas_widget  # only for testing
        # root canvas item should NOT be focusable or else it will grab focus in cases where no children have it.
        # no point in the root canvas item having focus.
        # self.__canvas_item.focusable = True
        # now construct the workspace
        selected_display_panel = None  # avoids warning
        display_panels: typing.List[DisplayPanel.DisplayPanel]
        try:
            display_panels = list()  # to be populated by _construct
            workspace_layout_d = workspace_layout.layout or dict()
            canvas_item, selected_display_panel = self._construct(workspace_layout_d, display_panels)
            # store the new workspace
            if canvas_item:
                self.__workspace = workspace_layout
                self.display_panels.extend(display_panels)
                assert self.__canvas_item  # for type checking
                self.__canvas_item.add_canvas_item(canvas_item)
                self.image_row.add(canvas_widget)
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
        if self.__workspace == None:  # handle error condition by creating known simple workspace and replacing bad one
            d = create_image_desc()
            d["selected"] = True
            workspace_layout.layout = d
            display_panels = list()  # to be populated by _construct
            canvas_item, selected_display_panel = self._construct(workspace_layout.layout, display_panels)
            # store the new workspace
            if canvas_item:
                self.__workspace = workspace_layout
                self.display_panels.extend(display_panels)
                assert self.__canvas_item  # for type checking
                self.__canvas_item.add_canvas_item(canvas_item)
                self.image_row.add(canvas_widget)
        self.document_controller.selected_display_panel = selected_display_panel
        self.document_controller.project.workspace_uuid = workspace_layout.uuid
        self.document_controller._workspace_changed(workspace_layout)

    def restore(self, workspace_uuid: typing.Optional[uuid.UUID]) -> None:
        """
            Restore the workspace to the given workspace_uuid.

            If workspace_uuid is None then create a new workspace and use it.
        """
        workspace = next((workspace for workspace in self._project.workspaces if workspace.uuid == workspace_uuid), None)
        if workspace is None:
            workspace = self.new_workspace()
        self._change_workspace(workspace)

    def change_to_previous_workspace(self) -> None:
        workspace_uuid = self.document_controller.project.workspace_uuid
        workspace = next((workspace for workspace in self._project.workspaces if workspace.uuid ==workspace_uuid), None)
        workspace_index = self._project.workspaces.index(workspace)
        workspace_index = (workspace_index - 1) % len(self._project.workspaces)
        self.change_workspace(self._project.workspaces[workspace_index])

    def change_to_next_workspace(self) -> None:
        workspace_uuid = self.document_controller.project.workspace_uuid
        workspace = next((workspace for workspace in self._project.workspaces if workspace.uuid == workspace_uuid), None)
        workspace_index = self._project.workspaces.index(workspace)
        workspace_index = (workspace_index + 1) % len(self._project.workspaces)
        self.change_workspace(self._project.workspaces[workspace_index])

    def new_workspace(self, name: typing.Optional[str] = None, layout: typing.Optional[Persistence.PersistentDictType] = None,
                      workspace_id: typing.Optional[str] = None,
                      index: typing.Optional[int] = None) -> WorkspaceLayout.WorkspaceLayout:
        """ Create a new workspace, insert into document_model, and return it. """
        workspace = WorkspaceLayout.WorkspaceLayout()
        self._project.insert_item("workspaces", index if index is not None else len(self._project.workspaces), workspace)
        d = create_image_desc()
        d["selected"] = True
        workspace.layout = layout if layout is not None else d
        workspace.name = name if name is not None else _("Workspace")
        if workspace_id:
            workspace.workspace_id = workspace_id
        return workspace

    def ensure_workspace(self, name: str, layout: Persistence.PersistentDictType, workspace_id: str) -> None:
        """Looks for a workspace with workspace_id.

        If none is found, create a new one, add it, and change to it.
        """
        workspace = next((workspace for workspace in self._project.workspaces if workspace.workspace_id == workspace_id), None)
        if not workspace:
            workspace = self.new_workspace(name=name, layout=layout, workspace_id=workspace_id)
        self._change_workspace(workspace)

    def get_workspace_layout_by_uuid(self, workspace_layout_uuid: uuid.UUID) -> typing.Optional[WorkspaceLayout.WorkspaceLayout]:
        for workspace_layout in self._project.workspaces:
            if workspace_layout.uuid == workspace_layout_uuid:
                return workspace_layout
        return None

    def pose_get_string_message_box(self, caption: str, text: str, accepted_fn: typing.Callable[[str], None],
                                    rejected_fn: typing.Optional[typing.Callable[[], None]] = None,
                                    accepted_text: typing.Optional[str] = None,
                                    rejected_text: typing.Optional[str] = None,
                                    message_box_id: typing.Optional[str] = None) -> typing.Optional[UserInterface.BoxWidget]:
        message_box_id = message_box_id if message_box_id else str(uuid.uuid4())
        if message_box_id in self.__message_boxes:
            return None
        if accepted_text is None: accepted_text = _("OK")
        if rejected_text is None: rejected_text = _("Cancel")
        message_box_widget = self.ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}
        caption_row = self.ui.create_row_widget()
        caption_row.add_spacing(12)
        caption_row.add(self.ui.create_label_widget(caption))
        caption_row.add_stretch()
        inside_row = self.ui.create_row_widget()

        def reject_button_clicked() -> bool:
            if rejected_fn: rejected_fn()
            async def remove_widget() -> None:
                self.message_column.remove(message_box_widget)
            self.document_controller.event_loop.create_task(remove_widget())
            assert message_box_id
            del self.__message_boxes[message_box_id]
            return False

        def accept_button_clicked() -> bool:
            accepted_fn(string_edit_widget.text or str())
            async def remove_widget() -> None:
                self.message_column.remove(message_box_widget)
            self.document_controller.event_loop.create_task(remove_widget())
            assert message_box_id
            del self.__message_boxes[message_box_id]
            return False

        # dummy to pass typing
        def reject_button_clicked_() -> None:
            reject_button_clicked()

        # dummy to pass typing
        def accept_button_clicked_() -> None:
            accept_button_clicked()

        string_edit_widget = self.ui.create_line_edit_widget()
        string_edit_widget.text = text
        string_edit_widget.on_return_pressed = accept_button_clicked
        string_edit_widget.on_escape_pressed = reject_button_clicked
        reject_button = self.ui.create_push_button_widget(rejected_text)
        reject_button.on_clicked = reject_button_clicked_
        accepted_button = self.ui.create_push_button_widget(accepted_text)
        accepted_button.on_clicked = accept_button_clicked_
        inside_row.add_spacing(12)
        inside_row.add(string_edit_widget)
        inside_row.add_spacing(12)
        inside_row.add(reject_button)
        inside_row.add_spacing(12)
        inside_row.add(accepted_button)
        inside_row.add_stretch()
        message_box_widget.add_spacing(6)
        message_box_widget.add(caption_row)
        message_box_widget.add_spacing(4)
        message_box_widget.add(inside_row)
        message_box_widget.add_spacing(4)
        self.message_column.add(message_box_widget)
        string_edit_widget.select_all()
        string_edit_widget.focused = True
        self.__message_boxes[message_box_id] = message_box_widget
        return message_box_widget

    def pose_confirmation_message_box(self, caption: str, accepted_fn: typing.Callable[[], None],
                                      rejected_fn: typing.Optional[typing.Callable[[], None]] = None,
                                      accepted_text: typing.Optional[str] = None,
                                      rejected_text: typing.Optional[str] = None, display_rejected: bool = True,
                                      message_box_id: typing.Optional[str] = None) -> typing.Optional[UserInterface.BoxWidget]:
        message_box_id = message_box_id if message_box_id else str(uuid.uuid4())
        if message_box_id in self.__message_boxes:
            return None
        if accepted_text is None: accepted_text = _("OK")
        if rejected_text is None: rejected_text = _("Cancel")
        message_box_widget = self.ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}

        def reject_button_clicked() -> None:
            if rejected_fn: rejected_fn()
            self.message_column.remove(message_box_widget)
            assert message_box_id
            del self.__message_boxes[message_box_id]

        def accept_button_clicked() -> None:
            accepted_fn()
            self.message_column.remove(message_box_widget)
            assert message_box_id
            del self.__message_boxes[message_box_id]

        reject_button = self.ui.create_push_button_widget(rejected_text)
        reject_button.on_clicked = reject_button_clicked
        accepted_button = self.ui.create_push_button_widget(accepted_text)
        accepted_button.on_clicked = accept_button_clicked
        caption_row = self.ui.create_row_widget()
        caption_row.add_spacing(12)
        caption_row.add(self.ui.create_label_widget(caption))
        if display_rejected:
            caption_row.add_spacing(12)
            caption_row.add(reject_button)
        caption_row.add_spacing(12)
        caption_row.add(accepted_button)
        caption_row.add_stretch()
        message_box_widget.add_spacing(6)
        message_box_widget.add(caption_row)
        message_box_widget.add_spacing(4)
        self.message_column.add(message_box_widget)
        self.__message_boxes[message_box_id] = message_box_widget
        return message_box_widget

    def pose_tool_tip_box(self, caption: str, timeout: float, message_box_id: typing.Optional[str] = None) -> typing.Optional[UserInterface.BoxWidget]:
        message_box_id = message_box_id if message_box_id else str(uuid.uuid4())
        if message_box_id in self.__message_boxes:
            return None
        accepted_text = '\u274C'
        message_box_widget = self.ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}
        lock = threading.Lock()
        def remove_box() -> None:
            with lock:
                if message_box_id in self.__message_boxes:
                    self.message_column.remove(message_box_widget)
                    assert message_box_id
                    del self.__message_boxes[message_box_id]

        def accept_button_clicked() -> None:
            remove_box()

        def wait_for_timeout() -> None:
            time.sleep(timeout)
            self.document_controller.queue_task(remove_box)

        accepted_button = self.ui.create_push_button_widget(accepted_text)
        accepted_button.on_clicked = accept_button_clicked
        caption_row = self.ui.create_row_widget()
        caption_row.add_spacing(12)
        caption_row.add(self.ui.create_label_widget(caption))
        caption_row.add_spacing(12)
        caption_row.add(accepted_button)
        caption_row.add_stretch()
        message_box_widget.add_spacing(6)
        message_box_widget.add(caption_row)
        message_box_widget.add_spacing(4)
        self.message_column.add(message_box_widget)
        self.__message_boxes[message_box_id] = message_box_widget
        threading.Thread(target=wait_for_timeout, daemon=True).start()
        setattr(message_box_widget, "remove_now", remove_box)  # argh. type checking.
        return message_box_widget

    def handle_drag_enter(self, display_panel: DisplayPanel.DisplayPanel, mime_data: UserInterface.MimeData) -> str:
        if mime_data.has_format(MimeTypes.DISPLAY_ITEM_MIME_TYPE):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        if mime_data.has_format(MimeTypes.DISPLAY_PANEL_MIME_TYPE):
            return "copy"
        return "ignore"

    def handle_drag_leave(self, display_panel: DisplayPanel.DisplayPanel) -> str:
        return "ignore"

    def handle_drag_move(self, display_panel: DisplayPanel.DisplayPanel, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
        if mime_data.has_format(MimeTypes.DISPLAY_ITEM_MIME_TYPE):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        if mime_data.has_format(MimeTypes.DISPLAY_PANEL_MIME_TYPE):
            return "copy"
        return "ignore"

    def should_handle_drag_for_mime_data(self, mime_data: UserInterface.MimeData) -> bool:
        return mime_data.has_format(MimeTypes.DISPLAY_ITEM_MIME_TYPE) or mime_data.has_format("text/uri-list") or mime_data.has_format(MimeTypes.DISPLAY_PANEL_MIME_TYPE)

    def handle_drop(self, display_panel: DisplayPanel.DisplayPanel, mime_data: UserInterface.MimeData, region: str, x: int, y: int) -> str:
        document_model = self.document_model
        if mime_data.has_format(MimeTypes.DISPLAY_PANEL_MIME_TYPE):
            display_item, d = MimeTypes.mime_data_get_panel(mime_data, self.document_model)
            if display_item and display_panel.handle_drop_display_item(region, display_item):
                pass  # already handled
            elif region == "right" or region == "left" or region == "top" or region == "bottom":
                command = self.insert_display_panel(display_panel, region, None, d)
                self.document_controller.push_undo_command(command)
            else:
                command = self.__replace_displayed_display_item(display_panel, None, d)
                self.document_controller.push_undo_command(command)
            return "move"
        display_item = MimeTypes.mime_data_get_display_item(mime_data, document_model)
        if display_item:
            if display_panel.handle_drop_display_item(region, display_item):
                pass  # already handled
            elif region == "right" or region == "left" or region == "top" or region == "bottom":
                command = self.insert_display_panel(display_panel, region, display_item)
                self.document_controller.push_undo_command(command)
            else:
                command = self.__replace_displayed_display_item(display_panel, display_item)
                self.document_controller.push_undo_command(command)
            return "copy"
        if mime_data.has_format("text/uri-list"):
            index = len(document_model.data_items)
            self.document_controller.receive_files(mime_data.file_paths, None, index, threaded=True, display_panel=display_panel)
            return "copy"
        return "ignore"

    def _replace_displayed_display_item(self, display_panel: DisplayPanel.DisplayPanel,
                                        display_item: typing.Optional[DisplayItem.DisplayItem],
                                        d: typing.Optional[Persistence.PersistentDictType] = None) -> Undo.UndoableCommand:
        return self.__replace_displayed_display_item(display_panel, display_item, d)

    def __replace_displayed_display_item(self, display_panel: DisplayPanel.DisplayPanel,
                                         display_item: typing.Optional[DisplayItem.DisplayItem],
                                         d: typing.Optional[Persistence.PersistentDictType] = None) -> Undo.UndoableCommand:
        """ Used in drag/drop support. """
        if self.document_controller.replaced_display_panel_content_flag:
            self.document_controller.replaced_display_panel_content = display_panel.save_contents()
        command = ChangeWorkspaceContentsCommand(self, _("Replace Display Panel"))
        if display_item:
            display_panel.set_display_panel_display_item(display_item, detect_controller=True)
        elif d is not None:
            display_panel.change_display_panel_content(d)
        display_panel.request_focus()
        self.__sync_layout()
        return command

    def insert_display_panel(self, display_panel: DisplayPanel.DisplayPanel, region: str,
                             display_item: typing.Optional[DisplayItem.DisplayItem] = None,
                             d: typing.Optional[Persistence.PersistentDictType] = None, new_uuid: typing.Optional[uuid.UUID] = None,
                             new_splits: typing.Optional[typing.List[float]] = None) -> Undo.UndoableCommand:
        assert self.__workspace
        command = ChangeWorkspaceContentsCommand(self, _("Split Display Panel"))
        self._insert_display_panel(display_panel, region, display_item, d, new_uuid, new_splits)
        return command

    def _insert_display_panel(self, display_panel: DisplayPanel.DisplayPanel, region: str,
                              display_item: typing.Optional[DisplayItem.DisplayItem], d: typing.Optional[Persistence.PersistentDictType],
                              new_uuid: typing.Optional[uuid.UUID],
                              new_splits: typing.Optional[typing.List[float]] = None) -> typing.Tuple[typing.Optional[typing.List[float]], typing.Optional[DisplayPanel.DisplayPanel]]:
        assert isinstance(display_panel, DisplayPanel.DisplayPanel)
        orientation = "vertical" if region in ("left", "right") else "horizontal"
        new_display_panel = None
        container = display_panel.container
        assert container
        # record old splits for undo if modifying an existing splitter; otherwise removing the display panel is trivial
        old_splits = list(container.splits) if isinstance(container, CanvasItem.SplitterCanvasItem) and container.orientation == orientation else None
        # if not modifying an existing splitter or if modifying in the other orientation, wrap panel in new splitter
        if not isinstance(container, CanvasItem.SplitterCanvasItem) or container.orientation != orientation:
            # check if trying to drag on non-axis edge of splitter
            # special case where top level item is the image panel
            splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation=orientation)
            splitter_canvas_item.on_splits_will_change = functools.partial(self._splits_will_change, splitter_canvas_item)
            splitter_canvas_item.on_splits_changed = functools.partial(self._splits_did_change, splitter_canvas_item)
            container.wrap_canvas_item(display_panel, splitter_canvas_item)
            container = splitter_canvas_item
        index = container.canvas_items.index(display_panel)
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            # modify the existing splitter
            old_split = container.splits[index] if not new_splits else 0.0
            new_index_adj = 1 if region == "right" or region == "bottom" else 0
            new_display_panel = DisplayPanel.DisplayPanel(self.document_controller, dict(), new_uuid)
            self.display_panels.insert(self.display_panels.index(display_panel) + new_index_adj, new_display_panel)
            if display_item:
                new_display_panel.set_display_panel_display_item(display_item, detect_controller=True)
            elif d is not None:
                new_display_panel.change_display_panel_content(d)
            container.insert_canvas_item(index + new_index_adj, new_display_panel)
            self.document_controller.selected_display_panel = new_display_panel
            # adjust the splits
            if new_splits:
                container.splits = copy.copy(new_splits)
            else:
                splits = list(container.splits)
                splits[index] = old_split * 0.5
                splits[index + 1] = old_split * 0.5
                container.splits = splits
            new_display_panel.request_focus()
        self.__sync_layout()
        return old_splits, new_display_panel

    def remove_display_panel(self, display_panel: DisplayPanel.DisplayPanel,
                             splits: typing.Optional[typing.List[float]] = None) -> Undo.UndoableCommand:
        assert self.__workspace
        command = ChangeWorkspaceContentsCommand(self, _("Remove Display Panel"))
        self._remove_display_panel(display_panel, splits)
        return command

    def _remove_display_panel(self, display_panel: DisplayPanel.DisplayPanel,
                              splits: typing.Optional[typing.List[float]]) -> typing.Tuple[typing.Optional[DisplayPanel.DisplayPanel], typing.Optional[typing.List[float]], str]:
        # first make sure the display panel has no content
        display_panel.change_display_panel_content({"type": "image", "display-panel-type": "empty-display-panel"})
        # now remove it
        container = display_panel.container
        region_id = str()
        old_display_panel: typing.Optional[DisplayPanel.DisplayPanel] = None
        old_splits: typing.Optional[typing.List[float]] = None
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            old_splits = list(container.splits)
            if display_panel in container.canvas_items:
                if len(container.canvas_items) > 1:
                    # configure the redo
                    display_panel_index = container.canvas_items.index(display_panel)
                    if display_panel_index > 0:
                        old_display_panel = typing.cast(DisplayPanel.DisplayPanel, container.canvas_items[display_panel_index - 1])
                        region_id = "right" if container.orientation == "vertical" else "bottom"
                    else:
                        old_display_panel = typing.cast(DisplayPanel.DisplayPanel, container.canvas_items[1])
                        region_id = "left" if container.orientation == "vertical" else "top"
                self.display_panels.remove(display_panel)
                container.remove_canvas_item(display_panel)
                if len(container.canvas_items) == 1:
                    container.unwrap_canvas_item(container.canvas_items[0])
                else:
                    if splits is not None:
                        container.splits = copy.copy(splits)
        self.__sync_layout()
        return old_display_panel, old_splits, region_id

    def apply_layout(self, display_panel: DisplayPanel.DisplayPanel, w: int, h: int) -> typing.List[DisplayPanel.DisplayPanel]:
        display_panel_container = display_panel.container
        assert display_panel_container
        assert self.__workspace
        change_workspace_contents_command = ChangeWorkspaceContentsCommand(self, _("Change Workspace Contents"))

        new_display_panels = list()

        # insert the rows
        row_splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation="horizontal")
        row_splitter_canvas_item.on_splits_will_change = functools.partial(self._splits_will_change, row_splitter_canvas_item)
        row_splitter_canvas_item.on_splits_changed = functools.partial(self._splits_did_change, row_splitter_canvas_item)
        display_panel_container.wrap_canvas_item(display_panel, row_splitter_canvas_item)
        new_display_panels.append(display_panel)
        dest_index = self.display_panels.index(display_panel)
        for row in range(h):
            if row > 0:
                row_display_panel = DisplayPanel.DisplayPanel(self.document_controller, dict())
                self.display_panels.insert(dest_index + 1, row_display_panel)
                new_display_panels.append(row_display_panel)
                dest_index += 1
                row_splitter_canvas_item.insert_canvas_item(row + 1, row_display_panel)
            else:
                row_display_panel = display_panel

            # insert the columns
            column_splitter_canvas_item = CanvasItem.SplitterCanvasItem(orientation="vertical")
            column_splitter_canvas_item.on_splits_will_change = functools.partial(self._splits_will_change, column_splitter_canvas_item)
            column_splitter_canvas_item.on_splits_changed = functools.partial(self._splits_did_change, column_splitter_canvas_item)
            row_display_panel_container = row_display_panel.container
            assert row_display_panel_container
            row_display_panel_container.wrap_canvas_item(row_display_panel, column_splitter_canvas_item)
            for column in range(1, w):
                column_display_panel = DisplayPanel.DisplayPanel(self.document_controller, dict())
                new_display_panels.append(column_display_panel)
                self.display_panels.insert(dest_index + 1, column_display_panel)
                dest_index += 1
                column_splitter_canvas_item.insert_canvas_item(column + 1, column_display_panel)
            column_splitter_canvas_item.splits = [1//w] * w

        row_splitter_canvas_item.splits = [1//h] * h

        self.__sync_layout()
        display_panel.request_focus()

        self.document_controller.push_undo_command(change_workspace_contents_command)

        return new_display_panels

    def _splits_will_change(self, splitter_canvas_item: CanvasItem.SplitterCanvasItem) -> None:
        self.__change_splitter_splits = list(splitter_canvas_item.splits)
        self.__change_splitter_command = ChangeWorkspaceContentsCommand(self, _("Change Workspace Contents"))

    def _splits_did_change(self, splitter_canvas_item: CanvasItem.SplitterCanvasItem) -> None:
        self.__sync_layout()
        if self.__change_splitter_command:
            if splitter_canvas_item.splits != self.__change_splitter_splits:
                self.document_controller.push_undo_command(self.__change_splitter_command)
            else:
                self.__change_splitter_command.close()
            self.__change_splitter_command = None
            self.__change_splitter_splits = list()

    def _sync_layout(self) -> None:
        self.__sync_layout()

    def __sync_layout(self) -> None:
        # ensure that the layout is written to persistent storage
        assert self.__workspace
        self.__workspace.layout = self._deconstruct(self.__canvas_item.canvas_items[0])


class WorkspaceManager(metaclass=Utility.Singleton):

    """
        The WorkspaceManager object keeps a list of workspaces and a list of panel
        types. It also creates workspace objects.
        """
    def __init__(self) -> None:
        self.__panel_tuples: typing.Dict[str, typing.Tuple[typing.Type[typing.Any], str, str, typing.List[str], str, typing.Optional[Persistence.PersistentDictType]]] = dict()

    def register_panel(self, panel_class: typing.Type[typing.Any], panel_id: str, name: str,
                       positions: typing.Sequence[str], position: str,
                       properties: typing.Optional[Persistence.PersistentDictType] = None) -> None:
        panel_tuple = panel_class, panel_id, name, list(positions), position, properties
        self.__panel_tuples[panel_id] = panel_tuple

    def unregister_panel(self, panel_id: str) -> None:
        del self.__panel_tuples[panel_id]

    def create_panel_content(self, document_controller: DocumentController.DocumentController, panel_id: str,
                             title: str, positions: typing.Sequence[str], position: str,
                             properties: typing.Optional[Persistence.PersistentDictType]) -> typing.Optional[Panel.Panel]:
        if panel_id in self.__panel_tuples:
            tuple = self.__panel_tuples[panel_id]
            cls = tuple[0]
            try:
                properties = properties if properties else {}
                panel = cls(document_controller, panel_id, properties)
                panel.create_dock_widget(title, positions, position)
                return typing.cast(Panel.Panel, panel)
            except Exception as e:
                import traceback
                print("Exception creating panel '" + panel_id + "': " + str(e))
                traceback.print_exc()
                traceback.print_stack()
        return None

    def register_filter_panel(self, filter_panel_class: typing.Optional[typing.Callable[[DocumentController.DocumentController], FilterPanel.FilterPanel]]) -> None:
        self.__filter_panel_class = filter_panel_class

    def create_filter_panel(self, document_controller: DocumentController.DocumentController) -> FilterPanel.FilterPanel:
        assert self.__filter_panel_class
        return self.__filter_panel_class(document_controller)

    def get_panel_info(self, panel_id: str) -> typing.Tuple[str, typing.Sequence[str], str, typing.Optional[Persistence.PersistentDictType]]:
        assert panel_id in self.__panel_tuples
        tuple = self.__panel_tuples[panel_id]
        return tuple[2], tuple[3], tuple[4], tuple[5]

    @property
    def panel_ids(self) -> typing.List[str]:
        return list(self.__panel_tuples.keys())
