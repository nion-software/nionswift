from __future__ import annotations

# standard libraries
import copy
import functools
import gettext
import random
import string
import typing
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DisplayPanel
from nion.swift import MimeTypes
from nion.swift import Undo
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.ui import CanvasItem
from nion.ui import UserInterface

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift import FilterPanel
    from nion.swift import Panel
    from nion.swift.model import DisplayItem
    from nion.swift.model import DocumentModel
    from nion.swift.model import Project


_ = gettext.gettext


def create_image_desc():
    return {"type": "image", "identifier": "".join([random.choice(string.ascii_uppercase) for _ in range(2)]), "uuid": str(uuid.uuid4())}


def create_splitter_desc(orientation: str, splits, children):
    return {"type": "splitter", "orientation": orientation, "splits": copy.copy(splits), "children": children}


class SplitDisplayPanelCommand(Undo.UndoableCommand):
    def __init__(self, workspace_controller: Workspace, workspace_layout: WorkspaceLayout.WorkspaceLayout,
                 modified_state: typing.Any, display_panel: DisplayPanel.DisplayPanel, region_id: str,
                 display_item: typing.Optional[DisplayItem.DisplayItem], old_splits: typing.Optional[typing.List[int]],
                 new_display_panel: DisplayPanel.DisplayPanel):
        super().__init__("Split Display Panel")
        self.__workspace_controller = workspace_controller
        self.__workspace_layout_uuid = workspace_layout.uuid
        self.__display_panel_uuid = display_panel.uuid
        self.__region_id = region_id
        self.__display_item_proxy = display_item.create_proxy() if display_item else None
        self.__d = None
        self.__old_splits = old_splits
        self.__new_display_panel_uuid = new_display_panel.uuid
        self.__uuid = new_display_panel.uuid
        self.initialize(modified_state)

    def close(self) -> None:
        self.__workspace_controller = None  # type: ignore
        self.__workspace_layout_uuid = None  # type: ignore
        self.__display_panel_uuid = None  # type: ignore
        self.__region_id = None  # type: ignore
        if self.__display_item_proxy:
            self.__display_item_proxy.close()
            self.__display_item_proxy = None  # type: ignore
        self.__d = None  # type: ignore
        self.__old_splits = None  # type: ignore
        self.__new_display_panel_uuid = None  # type: ignore
        self.__uuid = None  # type: ignore
        super().close()

    def _get_modified_state(self) -> typing.Any:
        workspace_layout = self.__workspace_controller.get_workspace_layout_by_uuid(self.__workspace_layout_uuid)
        assert workspace_layout
        return workspace_layout.modified_state, self.__workspace_controller._project.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        workspace_layout = self.__workspace_controller.get_workspace_layout_by_uuid(self.__workspace_layout_uuid)
        assert workspace_layout
        workspace_layout.modified_state, self.__workspace_controller._project.modified_state = modified_state

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    @property
    def _old_splits(self) -> typing.Optional[typing.List[int]]:
        return self.__old_splits

    def _undo(self) -> None:
        new_display_panel = self.__workspace_controller.get_display_panel_by_uuid(self.__new_display_panel_uuid)
        assert new_display_panel
        self.__d = new_display_panel.save_contents()
        self.__workspace_controller._remove_display_panel(new_display_panel, self.__old_splits)
        if self.__display_item_proxy:
            self.__display_item_proxy.close()
            self.__display_item_proxy = None

    def _redo(self) -> None:
        display_item = typing.cast(DisplayItem.DisplayItem, self.__display_item_proxy.item) if self.__display_item_proxy else None
        display_panel = self.__workspace_controller.get_display_panel_by_uuid(self.__display_panel_uuid)
        assert display_panel
        _, new_display_panel = self.__workspace_controller._insert_display_panel(display_panel, self.__region_id, display_item, self.__d, self.__uuid)
        assert new_display_panel
        self.__new_display_panel_uuid = new_display_panel.uuid


class RemoveDisplayPanelCommand(Undo.UndoableCommand):

    def __init__(self, workspace_controller: Workspace, workspace_layout: WorkspaceLayout.WorkspaceLayout,
                 modified_state: typing.Any, old_display_panel: DisplayPanel.DisplayPanel, region: str, d: dict,
                 old_uuid: uuid.UUID, old_splits: typing.Optional[typing.List[int]]):
        super().__init__("Remove Display Panel")
        self.__workspace_controller = workspace_controller
        self.__workspace_layout_uuid = workspace_layout.uuid
        self.__old_display_panel = old_display_panel  # canvas_item: always valid even in redo/undo
        self.__region = region
        self.__d = d
        self.__old_uuid = old_uuid
        self.__old_splits = old_splits
        self.__new_splits: typing.Optional[typing.List[int]] = None
        self.__new_display_panel_uuid: typing.Optional[uuid.UUID] = None
        self.initialize(modified_state)

    def close(self) -> None:
        self.__workspace_controller = None  # type: ignore
        self.__workspace_layout_uuid = None  # type: ignore
        self.__old_display_panel = None  # type: ignore
        self.__region = None  # type: ignore
        self.__d = None  # type: ignore
        self.__old_uuid = None  # type: ignore
        self.__old_splits = None  # type: ignore
        self.__new_splits = None  # type: ignore
        self.__new_display_panel_uuid = None  # type: ignore
        super().close()

    def _get_modified_state(self) -> typing.Any:
        workspace_layout = self.__workspace_controller.get_workspace_layout_by_uuid(self.__workspace_layout_uuid)
        assert workspace_layout
        return workspace_layout.modified_state, self.__workspace_controller._project.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        workspace_layout = self.__workspace_controller.get_workspace_layout_by_uuid(self.__workspace_layout_uuid)
        assert workspace_layout
        workspace_layout.modified_state, self.__workspace_controller._project.modified_state = modified_state

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self) -> None:
        assert self.__old_display_panel
        old_splits, new_display_panel = self.__workspace_controller._insert_display_panel(self.__old_display_panel, self.__region, None, self.__d, self.__old_uuid, self.__old_splits)
        assert new_display_panel
        self.__new_splits = old_splits
        self.__new_display_panel_uuid = new_display_panel.uuid

    def _redo(self) -> None:
        assert self.__new_display_panel_uuid
        new_display_panel = self.__workspace_controller.get_display_panel_by_uuid(self.__new_display_panel_uuid)
        assert new_display_panel
        old_display_panel, _, _ = self.__workspace_controller._remove_display_panel(new_display_panel, self.__new_splits)
        assert old_display_panel
        self.__old_display_panel = old_display_panel


class CreateWorkspaceCommand(Undo.UndoableCommand):
    def __init__(self, workspace_controller: Workspace, name: str):
        super().__init__("Create Workspace")
        self.__workspace_controller = workspace_controller
        self.__workspace_layout_uuid = workspace_controller._workspace.uuid
        self.__new_name = name
        self.__new_layout = None
        self.__new_workspace_id = None
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
        self.__new_workspace_id = None
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


class ChangeWorkspaceCommand(Undo.UndoableCommand):
    def __init__(self, workspace_controller: Workspace, workspace: WorkspaceLayout.WorkspaceLayout):
        super().__init__("Change Workspace")
        self.__workspace_controller = workspace_controller
        self.__old_workspace_uuid = workspace_controller._workspace.uuid
        self.__new_workspace = workspace
        self.initialize()

    def _get_modified_state(self) -> typing.Any:
        return self.__workspace_controller._project.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        self.__workspace_controller._project.modified_state = modified_state

    def perform(self) -> None:
        self.__workspace_controller._change_workspace(self.__new_workspace)

    def _undo(self) -> None:
        old_workspace = self.__workspace_controller.get_workspace_layout_by_uuid(self.__old_workspace_uuid)
        assert old_workspace
        self.__workspace_controller._change_workspace(old_workspace)

    def _redo(self) -> None:
        self.perform()


class ChangeWorkspaceContentsCommand(Undo.UndoableCommand):
    def __init__(self, workspace_controller: Workspace):
        super().__init__("Change Workspace Contents")
        self.__workspace_controller = workspace_controller
        self.__old_workspace_layout = workspace_controller.deconstruct()
        self.__new_workspace_layout = typing.cast(dict, None)
        self.initialize()

    def _get_modified_state(self) -> typing.Any:
        return self.__workspace_controller._project.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        self.__workspace_controller._project.modified_state = modified_state

    def _undo(self) -> None:
        self.__new_workspace_layout = self.__workspace_controller.deconstruct()
        self.__workspace_controller.reconstruct(self.__old_workspace_layout)

    def _redo(self) -> None:
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

        self.ui = self.document_controller.ui

        self.workspace_manager = WorkspaceManager()

        self.workspace_id = workspace_id

        self.dock_panels: typing.List[Panel.Panel] = []
        self.display_panels: typing.List[DisplayPanel.DisplayPanel] = []

        self.__canvas_item = None

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
        self.__change_splitter_splits = None

    def close(self) -> None:
        for message_box_widget in copy.copy(list(self.__message_boxes.values())):
            self.message_column.remove(message_box_widget)
        self.__message_boxes.clear()
        if self.__workspace:
            self.__sync_layout()
        self.display_panels = []
        self.__canvas_item = None
        self.__workspace = None
        for dock_panel in self.dock_panels:
            dock_panel.close()
        self.__content_column = None
        self.filter_row = None
        self.image_row = None
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
    def _canvas_item(self) -> typing.Optional[CanvasItem.CanvasItemComposition]:
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
                     positions: typing.Sequence[str], position: str, properties: dict) -> typing.Optional[Panel.Panel]:
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

    def display_display_item_in_display_panel(self, display_item, display_panel_id):
        for display_panel in self.display_panels:
            if display_panel.display_panel_id == display_panel_id:
                display_panel.set_display_panel_display_item(display_item)
                self.__sync_layout()

    def _construct(self, desc: dict, display_panels: typing.List[DisplayPanel.DisplayPanel]) -> typing.Tuple[typing.Optional[CanvasItem.AbstractCanvasItem], typing.Optional[DisplayPanel.DisplayPanel]]:
        selected_display_panel = None
        type = desc["type"]
        container = None
        item = None
        post_children_adjust = lambda: None
        if type == "container":
            container = CanvasItem.CanvasItemComposition()
        elif type == "splitter":
            container = CanvasItem.SplitterCanvasItem(orientation=desc.get("orientation"))
            container.on_splits_will_change = functools.partial(self._splits_will_change, container)
            container.on_splits_changed = functools.partial(self._splits_did_change, container)
            def splitter_post_children_adjust():
                splits = desc.get("splits")
                if splits is not None:
                    container.splits = splits
            post_children_adjust = splitter_post_children_adjust
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
                container.add_canvas_item(child_canvas_item)
                selected_display_panel = child_selected_display_panel if child_selected_display_panel else selected_display_panel
            post_children_adjust()
            return container, selected_display_panel
        return item, selected_display_panel

    def deconstruct(self) -> dict:
        assert self.__canvas_item
        return self._deconstruct(self.__canvas_item.canvas_items[0])

    def reconstruct(self, d: dict) -> typing.Optional[DisplayPanel.DisplayPanel]:
        assert self.__canvas_item
        return self._reconstruct(d, self.__canvas_item.canvas_items[0])

    def _reconstruct(self, d: dict, canvas_item: CanvasItem.AbstractCanvasItem) -> typing.Optional[DisplayPanel.DisplayPanel]:
        selected_display_panel = None
        type = d["type"]
        container = None
        if type == "container":
            assert isinstance(canvas_item, CanvasItem.CanvasItemComposition)
            container = canvas_item
        elif type == "splitter":
            assert isinstance(canvas_item, CanvasItem.SplitterCanvasItem)
            container = canvas_item
            splits = d.get("splits")
            if splits is not None:
                container.splits = splits
        elif type == "image":
            assert isinstance(canvas_item, DisplayPanel.DisplayPanel)
            display_panel = canvas_item
            display_panel.change_display_panel_content(d)
            if d.get("selected", False):
                selected_display_panel = display_panel
        if container:
            children = d.get("children", list())
            for child_desc, child_canvas_item in zip(children, container.canvas_items):
                child_selected_display_panel = self._reconstruct(child_desc, child_canvas_item)
                selected_display_panel = child_selected_display_panel if child_selected_display_panel else selected_display_panel
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

    def _deconstruct(self, canvas_item: CanvasItem.AbstractCanvasItem) -> dict:
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
    def _workspace_layout(self) -> dict:
        return self.deconstruct()

    def change_workspace(self, workspace: WorkspaceLayout.WorkspaceLayout) -> None:
        command = ChangeWorkspaceCommand(self, workspace)
        command.perform()
        self.document_controller.push_undo_command(command)

    def _change_workspace(self, workspace: WorkspaceLayout.WorkspaceLayout) -> None:
        assert workspace is not None
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
            canvas_item, selected_display_panel = self._construct(workspace.layout, display_panels)
            # store the new workspace
            if canvas_item:
                self.__workspace = workspace
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
            workspace.layout = d
            display_panels = list()  # to be populated by _construct
            canvas_item, selected_display_panel = self._construct(workspace.layout, display_panels)
            # store the new workspace
            if canvas_item:
                self.__workspace = workspace
                self.display_panels.extend(display_panels)
                assert self.__canvas_item  # for type checking
                self.__canvas_item.add_canvas_item(canvas_item)
                self.image_row.add(canvas_widget)
        self.document_controller.selected_display_panel = selected_display_panel
        self.document_controller.project.workspace_uuid = workspace.uuid
        self.document_controller._workspace_changed(workspace)

    def restore(self, workspace_uuid: uuid.UUID) -> None:
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

    def new_workspace(self, name: typing.Optional[str] = None, layout: typing.Optional[dict] = None,
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

    def ensure_workspace(self, name: str, layout: dict, workspace_id: str) -> None:
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

    def create_workspace(self) -> None:
        """ Pose a dialog to name and create a workspace. """

        def create_clicked(text: str) -> None:
            if text:
                command = CreateWorkspaceCommand(self, text)
                command.perform()
                self.document_controller.push_undo_command(command)

        self.pose_get_string_message_box(caption=_("Enter a name for the workspace"), text=_("Workspace"),
                                         accepted_fn=create_clicked, accepted_text=_("Create"),
                                         message_box_id="create_workspace")

    def rename_workspace(self) -> None:
        """ Pose a dialog to rename the workspace. """
        assert self.__workspace

        def rename_clicked(text: str) -> None:
            if len(text) > 0:
                command = RenameWorkspaceCommand(self, text)
                command.perform()
                self.document_controller.push_undo_command(command)

        self.pose_get_string_message_box(caption=_("Enter new name for workspace"), text=self.__workspace.name,
                                         accepted_fn=rename_clicked, accepted_text=_("Rename"),
                                         message_box_id="rename_workspace")

    def remove_workspace(self) -> None:
        """ Pose a dialog to confirm removal then remove workspace. """
        assert self.__workspace

        def confirm_clicked() -> None:
            if len(self._project.workspaces) > 1:
                command = RemoveWorkspaceCommand(self)
                command.perform()
                self.document_controller.push_undo_command(command)

        caption = _("Remove workspace named '{0}'?").format(self.__workspace.name)
        self.pose_confirmation_message_box(caption, confirm_clicked, accepted_text=_("Remove Workspace"),
                                           message_box_id="remove_workspace")

    def clone_workspace(self) -> None:
        """ Pose a dialog to name and clone a workspace. """
        assert self.__workspace

        def clone_clicked(text: str) -> None:
            if text:
                command = CloneWorkspaceCommand(self, text)
                command.perform()
                self.document_controller.push_undo_command(command)

        self.pose_get_string_message_box(caption=_("Enter a name for the workspace"), text=self.__workspace.name,
                                         accepted_fn=clone_clicked, accepted_text=_("Clone"),
                                         message_box_id="clone_workspace")

    def pose_get_string_message_box(self, caption: str, text: str, accepted_fn: typing.Callable[[str], None],
                                    rejected_fn: typing.Optional[typing.Callable[[], None]] = None,
                                    accepted_text: typing.Optional[str] = None,
                                    rejected_text: typing.Optional[str] = None,
                                    message_box_id: typing.Optional[str] = None) -> typing.Optional[UserInterface.Widget]:
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

        def reject_button_clicked():
            if rejected_fn: rejected_fn()
            async def remove_widget():
                self.message_column.remove(message_box_widget)
            self.document_controller.event_loop.create_task(remove_widget())
            del self.__message_boxes[message_box_id]
            return False

        def accept_button_clicked():
            accepted_fn(string_edit_widget.text)
            async def remove_widget():
                self.message_column.remove(message_box_widget)
            self.document_controller.event_loop.create_task(remove_widget())
            del self.__message_boxes[message_box_id]
            return False

        string_edit_widget = self.ui.create_line_edit_widget()
        string_edit_widget.text = text
        string_edit_widget.on_return_pressed = accept_button_clicked
        string_edit_widget.on_escape_pressed = reject_button_clicked
        reject_button = self.ui.create_push_button_widget(rejected_text)
        reject_button.on_clicked = reject_button_clicked
        accepted_button = self.ui.create_push_button_widget(accepted_text)
        accepted_button.on_clicked = accept_button_clicked
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
                                      message_box_id: typing.Optional[str] = None) -> typing.Optional[UserInterface.Widget]:
        message_box_id = message_box_id if message_box_id else str(uuid.uuid4())
        if message_box_id in self.__message_boxes:
            return None
        if accepted_text is None: accepted_text = _("OK")
        if rejected_text is None: rejected_text = _("Cancel")
        message_box_widget = self.ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}

        def reject_button_clicked():
            if rejected_fn: rejected_fn()
            self.message_column.remove(message_box_widget)
            del self.__message_boxes[message_box_id]

        def accept_button_clicked():
            accepted_fn()
            self.message_column.remove(message_box_widget)
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

    def pose_tool_tip_box(self, caption: str, timeout: float, message_box_id: typing.Optional[str]=None) -> typing.Optional[UserInterface.Widget]:
        import threading
        import time
        message_box_id = message_box_id if message_box_id else str(uuid.uuid4())
        if message_box_id in self.__message_boxes:
            return None
        accepted_text = '\u274C'
        message_box_widget = self.ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}
        lock = threading.Lock()
        def remove_box():
            with lock:
                if message_box_id in self.__message_boxes:
                    self.message_column.remove(message_box_widget)
                    del self.__message_boxes[message_box_id]

        def accept_button_clicked():
            remove_box()

        def wait_for_timeout():
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
        message_box_widget.remove_now = remove_box
        return message_box_widget

    def handle_drag_enter(self, display_panel: DisplayPanel.DisplayPanel, mime_data: UserInterface.MimeData) -> str:
        if mime_data.has_format(MimeTypes.DISPLAY_ITEM_MIME_TYPE):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        if mime_data.has_format(MimeTypes.DISPLAY_PANEL_MIME_TYPE):
            return "copy"
        return "ignore"

    def handle_drag_leave(self, display_panel: DisplayPanel.DisplayPanel) -> bool:
        return False

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

    def handle_drop(self, display_panel: DisplayPanel.DisplayPanel, mime_data: UserInterface.MimeData, region, x: int, y: int) -> str:
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
                                        d: typing.Optional[dict] = None) -> Undo.UndoableCommand:
        return self.__replace_displayed_display_item(display_panel, display_item, d)

    def __replace_displayed_display_item(self, display_panel: DisplayPanel.DisplayPanel,
                                         display_item: typing.Optional[DisplayItem.DisplayItem],
                                         d: typing.Optional[dict] = None) -> Undo.UndoableCommand:
        """ Used in drag/drop support. """
        self.document_controller.replaced_display_panel_content = display_panel.save_contents()
        command = DisplayPanel.ReplaceDisplayPanelCommand(self)
        if display_item:
            display_panel.set_display_panel_display_item(display_item, detect_controller=True)
        elif d is not None:
            display_panel.change_display_panel_content(d)
        display_panel.request_focus()
        self.__sync_layout()
        return command

    def insert_display_panel(self, display_panel: DisplayPanel.DisplayPanel, region: str,
                             display_item: typing.Optional[DisplayItem.DisplayItem] = None,
                             d: typing.Optional[dict] = None, new_uuid: typing.Optional[uuid.UUID] = None,
                             new_splits: typing.Optional[typing.List[int]] = None) -> Undo.UndoableCommand:
        assert self.__workspace
        modified_state = self.__workspace.modified_state, self._project.modified_state
        old_splits, new_display_panel = self._insert_display_panel(display_panel, region, display_item, d, new_uuid, new_splits)
        assert new_display_panel
        return SplitDisplayPanelCommand(self, self.__workspace, modified_state, display_panel, region, display_item, old_splits, new_display_panel)

    def _insert_display_panel(self, display_panel: DisplayPanel.DisplayPanel, region: str,
                              display_item: typing.Optional[DisplayItem.DisplayItem], d: typing.Optional[dict],
                              new_uuid: typing.Optional[uuid.UUID],
                              new_splits: typing.Optional[typing.List[int]] = None) -> typing.Tuple[typing.Optional[typing.List[int]], typing.Optional[DisplayPanel.DisplayPanel]]:
        assert isinstance(display_panel, DisplayPanel.DisplayPanel)
        orientation = "vertical" if region in ("left", "right") else "horizontal"
        new_display_panel = None
        container = display_panel.container
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
            old_split = container.splits[index] if not new_splits else None
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
                             splits: typing.Optional[typing.List[int]] = None) -> Undo.UndoableCommand:
        # save the old display panel
        assert self.__workspace
        d = display_panel.save_contents()
        modified_state = self.__workspace.modified_state, self._project.modified_state
        old_display_panel, old_splits, region_id = self._remove_display_panel(display_panel, splits)
        assert old_display_panel
        return RemoveDisplayPanelCommand(self, self.__workspace, modified_state, old_display_panel, region_id, d, display_panel.uuid, old_splits)

    def _remove_display_panel(self, display_panel: DisplayPanel.DisplayPanel,
                              splits: typing.Optional[typing.List[int]]) -> typing.Tuple[typing.Optional[DisplayPanel.DisplayPanel], typing.Optional[typing.List[int]], str]:
        # first make sure the display panel has no content
        display_panel.change_display_panel_content({"type": "image", "display-panel-type": "empty-display-panel"})
        # now remove it
        container = display_panel.container
        region_id = str()
        old_display_panel = None
        old_splits = None
        if isinstance(container, CanvasItem.SplitterCanvasItem):
            old_splits = container.splits
            if display_panel in container.canvas_items:
                if len(container.canvas_items) > 1:
                    # configure the redo
                    display_panel_index = container.canvas_items.index(display_panel)
                    if display_panel_index > 0:
                        old_display_panel = container.canvas_items[display_panel_index - 1]
                        region_id = "right" if container.orientation == "vertical" else "bottom"
                    else:
                        old_display_panel = container.canvas_items[1]
                        region_id = "left" if container.orientation == "vertical" else "top"
                self.display_panels.remove(display_panel)
                container.remove_canvas_item(display_panel)
                if len(container.canvas_items) == 1:
                    container.unwrap_canvas_item(container.canvas_items[0])
                else:
                    if splits:
                        container.splits = copy.copy(splits)
        self.__sync_layout()
        return old_display_panel, old_splits, region_id

    def selected_display_panel_changed(self, selected_display_panel: DisplayPanel.DisplayPanel) -> None:
        for display_panel in self.display_panels:
            display_panel.set_selected(display_panel == selected_display_panel)

    def _splits_will_change(self, splitter_canvas_item: CanvasItem.SplitterCanvasItem) -> None:
        self.__change_splitter_splits = splitter_canvas_item.splits
        self.__change_splitter_command = ChangeWorkspaceContentsCommand(self)

    def _splits_did_change(self, splitter_canvas_item: CanvasItem.SplitterCanvasItem) -> None:
        self.__sync_layout()
        if self.__change_splitter_command:
            if splitter_canvas_item.splits != self.__change_splitter_splits:
                self.document_controller.push_undo_command(self.__change_splitter_command)
            else:
                self.__change_splitter_command.close()
            self.__change_splitter_command = None
            self.__change_splitter_splits = None

    def __sync_layout(self) -> None:
        # ensure that the layout is written to persistent storage
        assert self.__workspace
        assert self.__canvas_item
        self.__workspace.layout = self._deconstruct(self.__canvas_item.canvas_items[0])


class WorkspaceManager(metaclass=Utility.Singleton):

    """
        The WorkspaceManager object keeps a list of workspaces and a list of panel
        types. It also creates workspace objects.
        """
    def __init__(self):
        self.__panel_tuples = {}

    def register_panel(self, panel_class, panel_id: str, name: str, positions: typing.List[str], position: str, properties: typing.Optional[dict]=None) -> None:
        panel_tuple = panel_class, panel_id, name, positions, position, properties
        self.__panel_tuples[panel_id] = panel_tuple

    def unregister_panel(self, panel_id: str) -> None:
        del self.__panel_tuples[panel_id]

    def create_panel_content(self, document_controller: DocumentController.DocumentController, panel_id: str,
                             title: str, positions: typing.Sequence[str], position: str, properties: dict) -> typing.Optional[Panel.Panel]:
        if panel_id in self.__panel_tuples:
            tuple = self.__panel_tuples[panel_id]
            cls = tuple[0]
            try:
                properties = properties if properties else {}
                panel = cls(document_controller, panel_id, properties)
                panel.create_dock_widget(title, positions, position)
                return panel
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

    def get_panel_info(self, panel_id: str) -> typing.Tuple:
        assert panel_id in self.__panel_tuples
        tuple = self.__panel_tuples[panel_id]
        return tuple[2], tuple[3], tuple[4], tuple[5]

    @property
    def panel_ids(self) -> typing.List[str]:
        return list(self.__panel_tuples.keys())
