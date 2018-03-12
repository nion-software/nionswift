# standard libraries
import contextlib
import copy
import json
import logging
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DisplayPanel
from nion.swift import DocumentController
from nion.swift import Workspace
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.test import DocumentController_test
from nion.ui import CanvasItem
from nion.ui import TestUI
from nion.utils import Geometry



def get_layout(layout_id):
    uuid1 = "0569ca31-afd7-48bd-ad54-5e2bb9f21102"
    uuid2 = "acd77f9f-2f6f-4fbf-af5e-94330b73b997"
    uuid3 = "3541821d-221a-40c5-82fa-d8188157f7bd"
    uuid4 = "c2215359-786b-4ba6-aa62-87b124a3705e"
    uuid5 = "f0ac94db-3a98-4eea-84e3-6e8b408ec5cd"
    uuid6 = "307dd234-8295-4dc3-b339-4e402bf69d6e"
    if layout_id == "2x1":
        d = {"type": "splitter", "orientation": "vertical", "splits": [0.5, 0.5],
            "children": [{"type": "image", "uuid": uuid1, "identifier": "a", "selected": True},
                {"type": "image", "uuid": uuid2, "identifier": "b"}]}
    elif layout_id == "1x2":
        d = {"type": "splitter", "orientation": "horizontal", "splits": [0.5, 0.5],
            "children": [{"type": "image", "uuid": uuid1, "identifier": "a", "selected": True},
                {"type": "image", "uuid": uuid2, "identifier": "b"}]}
    elif layout_id == "1x2x2":
        d = {"type": "splitter", "orientation": "horizontal", "splits": [0.5, 0.5], "children": [
            {"type": "splitter", "orientation": "vertical", "splits": [0.5, 0.5],
                "children": [{"type": "image", "uuid": uuid1, "identifier": "a", "selected": True},
                    {"type": "image", "uuid": uuid2, "identifier": "b"}]},
            {"type": "image", "uuid": uuid3, "identifier": "c"}]}
    elif layout_id == "3x1":
        d = {"type": "splitter", "orientation": "vertical", "splits": [1.0 / 3, 1.0 / 3, 1.0 / 3],
            "children": [{"type": "image", "uuid": uuid1, "identifier": "a", "selected": True},
                {"type": "image", "uuid": uuid2, "identifier": "b"},
                {"type": "image", "uuid": uuid2, "identifier": "c"}]}
    elif layout_id == "2x2":
        d = {"type": "splitter", "orientation": "horizontal", "splits": [0.5, 0.5], "children": [
            {"type": "splitter", "orientation": "vertical", "splits": [0.5, 0.5],
                "children": [{"type": "image", "uuid": uuid1, "identifier": "a", "selected": True},
                    {"type": "image", "uuid": uuid2, "identifier": "b"}]},
            {"type": "splitter", "orientation": "vertical", "splits": [0.5, 0.5],
                "children": [{"type": "image", "uuid": uuid3, "identifier": "c"},
                    {"type": "image", "uuid": uuid4, "identifier": "d"}]}]}
    elif layout_id == "3x2":
        d = {"type": "splitter", "orientation": "vertical", "splits": [1.0 / 3, 1.0 / 3, 1.0 / 3], "children": [
            {"type": "splitter", "orientation": "horizontal", "splits": [0.5, 0.5],
                "children": [{"type": "image", "uuid": uuid1, "identifier": "a", "selected": True},
                    {"type": "image", "uuid": uuid2, "identifier": "b"}]},
            {"type": "splitter", "orientation": "horizontal", "splits": [0.5, 0.5],
                "children": [{"type": "image", "uuid": uuid3, "identifier": "c"},
                    {"type": "image", "uuid": uuid4, "identifier": "d"}]},
            {"type": "splitter", "orientation": "horizontal", "splits": [0.5, 0.5],
                "children": [{"type": "image", "uuid": uuid5, "identifier": "e"},
                    {"type": "image", "uuid": uuid6, "identifier": "f"}]}]}
    else:  # default 1x1
        layout_id = "1x1"
        d = {"type": "image", "uuid": uuid1, "identifier": "a", "selected": True}
    return layout_id, d


class MimeData:
    def __init__(self, type, content):
        self.type = type
        self.content = content
    def has_format(self, format_str):
        return format_str == self.type
    def data_as_string(self, format_str):
        return self.content


class TestWorkspaceClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_basic_change_layout_results_in_correct_image_panel_count(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_1x1 = document_controller.document_model.workspaces[0]
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            workspace_3x1 = document_controller.workspace_controller.new_workspace(*get_layout("3x1"))
            workspace_2x2 = document_controller.workspace_controller.new_workspace(*get_layout("2x2"))
            workspace_3x2 = document_controller.workspace_controller.new_workspace(*get_layout("3x2"))
            workspace_1x2 = document_controller.workspace_controller.new_workspace(*get_layout("1x2"))
            self.assertEqual(len(document_controller.document_model.workspaces), 6)
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 1)
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 1)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            document_controller.workspace_controller.change_workspace(workspace_3x1)
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 3)
            document_controller.workspace_controller.change_workspace(workspace_2x2)
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 4)
            document_controller.workspace_controller.change_workspace(workspace_3x2)
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 6)
            document_controller.workspace_controller.change_workspace(workspace_1x2)
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 1)

    def test_basic_change_layout_results_in_image_panel_being_destructed(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_1x1 = document_controller.document_model.workspaces[0]
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            image_panel_weak_ref = weakref.ref(document_controller.workspace_controller.display_panels[0])
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            self.assertIsNone(image_panel_weak_ref())

    def test_image_panel_focused_when_clicked(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item2)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # click in first panel
            modifiers = CanvasItem.KeyboardModifiers()
            root_canvas_item.canvas_widget.simulate_mouse_click(160, 240, modifiers)
            self.assertTrue(document_controller.workspace_controller.display_panels[0]._is_focused())
            self.assertTrue(document_controller.workspace_controller.display_panels[0]._is_selected())
            self.assertFalse(document_controller.workspace_controller.display_panels[1]._is_focused())
            self.assertFalse(document_controller.workspace_controller.display_panels[1]._is_selected())
            # now click the second panel
            root_canvas_item.canvas_widget.simulate_mouse_click(480, 240, modifiers)
            self.assertFalse(document_controller.workspace_controller.display_panels[0]._is_focused())
            self.assertFalse(document_controller.workspace_controller.display_panels[0]._is_selected())
            self.assertTrue(document_controller.workspace_controller.display_panels[1]._is_focused())
            self.assertTrue(document_controller.workspace_controller.display_panels[1]._is_selected())
            # and back to the first panel
            modifiers = CanvasItem.KeyboardModifiers()
            root_canvas_item.canvas_widget.simulate_mouse_click(160, 240, modifiers)
            self.assertTrue(document_controller.workspace_controller.display_panels[0]._is_focused())
            self.assertTrue(document_controller.workspace_controller.display_panels[0]._is_selected())
            self.assertFalse(document_controller.workspace_controller.display_panels[1]._is_focused())
            self.assertFalse(document_controller.workspace_controller.display_panels[1]._is_selected())

    def test_empty_image_panel_focused_when_clicked(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # click in first panel
            modifiers = CanvasItem.KeyboardModifiers()
            root_canvas_item.canvas_widget.simulate_mouse_click(160, 240, modifiers)
            self.assertTrue(document_controller.workspace_controller.display_panels[0]._is_focused())
            self.assertTrue(document_controller.workspace_controller.display_panels[0]._is_selected())
            self.assertFalse(document_controller.workspace_controller.display_panels[1]._is_focused())
            self.assertFalse(document_controller.workspace_controller.display_panels[1]._is_selected())

    def test_changed_image_panel_focused_when_clicked(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # click in right panel and change the display type
            modifiers = CanvasItem.KeyboardModifiers()
            root_canvas_item.canvas_widget.simulate_mouse_click(480, 240, modifiers)
            self.assertFalse(document_controller.workspace_controller.display_panels[0]._is_focused())
            self.assertFalse(document_controller.workspace_controller.display_panels[0]._is_selected())
            self.assertTrue(document_controller.workspace_controller.display_panels[1]._is_focused())
            self.assertTrue(document_controller.workspace_controller.display_panels[1]._is_selected())
            document_controller.selected_display_panel.change_display_panel_content({"type": "image"})
            root_canvas_item.refresh_layout_immediate()
            # click in left panel, make sure focus/selected are right
            root_canvas_item.canvas_widget.simulate_mouse_click(160, 240, modifiers)
            self.assertTrue(document_controller.workspace_controller.display_panels[0]._is_focused())
            self.assertTrue(document_controller.workspace_controller.display_panels[0]._is_selected())
            self.assertFalse(document_controller.workspace_controller.display_panels[1]._is_focused())
            self.assertFalse(document_controller.workspace_controller.display_panels[1]._is_selected())
            root_canvas_item.refresh_layout_immediate()
            # click in right panel, make sure focus/selected are right
            root_canvas_item.canvas_widget.simulate_mouse_click(480, 240, modifiers)
            self.assertFalse(document_controller.workspace_controller.display_panels[0]._is_focused())
            self.assertFalse(document_controller.workspace_controller.display_panels[0]._is_selected())
            self.assertTrue(document_controller.workspace_controller.display_panels[1]._is_focused())
            self.assertTrue(document_controller.workspace_controller.display_panels[1]._is_selected())

    def test_workspace_construct_and_deconstruct_result_in_matching_descriptions(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # deconstruct
            desc1 = get_layout("2x1")[1]
            desc2 = document_controller.workspace_controller._deconstruct(root_canvas_item.canvas_items[0].canvas_items[0])
            self.assertEqual(desc1, desc2)

    def test_workspace_change_records_workspace_uuid(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_1x1 = document_controller.document_model.workspaces[0]
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            self.assertEqual(document_controller.document_model.workspace_uuid, workspace_1x1.uuid)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            self.assertEqual(document_controller.document_model.workspace_uuid, workspace_2x1.uuid)
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            self.assertEqual(document_controller.document_model.workspace_uuid, workspace_1x1.uuid)

    def test_workspace_change_records_workspace_data_item_contents(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_1x1 = document_controller.document_model.workspaces[0]
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item3 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item2)
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item3)
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item1)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item3)

    def test_workspace_records_json_compatible_content_when_closing_document(self):
        library_storage = DocumentModel.FilePersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_1x1 = document_controller.document_model.workspaces[0]
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
        json_str = json.dumps(library_storage.properties)
        properties = json.loads(json_str)
        self.assertEqual(properties, library_storage.properties)

    def test_workspace_saves_contents_immediately_following_change(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom")
            # copy the storage before the document closes
            library_storage_0 = copy.deepcopy(library_storage.properties)
        # reload with the storage copied before the document closes
        document_model = DocumentModel.DocumentModel(library_storage=DocumentModel.MemoryPersistentStorage(library_storage_0))
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_controller = document_controller.workspace_controller
            self.assertEqual(2, len(workspace_controller.display_panels))

    def test_workspace_saves_contents_immediately_following_adjustment(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_controller = document_controller.workspace_controller
            workspace_2x1 = workspace_controller.new_workspace(*get_layout("2x1"))
            workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            display_panel = workspace_controller.display_panels[0]
            display_panel.container.on_splits_will_change()
            display_panel.container.splits = [0.4, 0.6]
            display_panel.container.on_splits_changed()
            # copy the storage before the document closes
            library_storage_0 = copy.deepcopy(library_storage.properties)
        # reload with the storage copied before the document closes
        document_model = DocumentModel.DocumentModel(library_storage=DocumentModel.MemoryPersistentStorage(library_storage_0))
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual([0.4, 0.6], display_panel.container.splits)

    def test_workspace_saves_contents_immediately_following_controller_change(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_controller = document_controller.workspace_controller
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            display_panel = workspace_controller.display_panels[0]
            d = {"type": "image", "controller_type": "test"}
            display_panel.change_display_panel_content(d)
            # copy the storage before the document closes
            library_storage_0 = copy.deepcopy(library_storage.properties)
        # reload with the storage copied before the document closes
        document_model = DocumentModel.DocumentModel(library_storage=DocumentModel.MemoryPersistentStorage(library_storage_0))
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual("test", display_panel.save_contents()["controller_type"])
        DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_workspace_saves_contents_immediately_following_view_change(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_controller = document_controller.workspace_controller
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            display_panel = workspace_controller.display_panels[0]
            d = {"type": "image", "display-panel-type": "browser-display-panel"}
            display_panel.change_display_panel_content(d)
            # copy the storage before the document closes
            library_storage_0 = copy.deepcopy(library_storage.properties)
        # reload with the storage copied before the document closes
        document_model = DocumentModel.DocumentModel(library_storage=DocumentModel.MemoryPersistentStorage(library_storage_0))
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual("grid", display_panel.save_contents()["browser_type"])

    def test_workspace_insert_into_no_splitter_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # insert a new display
            command = workspace_controller.insert_display_panel(display_panel, "bottom")
            document_controller.push_undo_command(command)
            document_controller.selected_display_panel = display_panel
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # undo the insert
            document_controller.handle_undo()
            document_controller.selected_display_panel = display_panel
            # compare against old layout
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # now redo
            document_controller.handle_redo()
            document_controller.selected_display_panel = display_panel
            # compare against new layout
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_insert_into_splitter_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            document_controller.selected_display_panel = display_panel
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # insert a new display
            command = workspace_controller.insert_display_panel(display_panel, "bottom")
            document_controller.push_undo_command(command)
            document_controller.selected_display_panel = display_panel
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # undo the insert
            document_controller.handle_undo()
            document_controller.selected_display_panel = display_panel
            # compare against old layout
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # now redo
            document_controller.handle_redo()
            document_controller.selected_display_panel = display_panel
            # compare against new layout
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_remove_from_splitter_with_two_items_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            document_controller.selected_display_panel = display_panel
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # remove display
            command = workspace_controller.remove_display_panel(display_panel)
            document_controller.push_undo_command(command)
            document_controller.selected_display_panel = display_panel
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # undo the remove
            document_controller.handle_undo()
            document_controller.selected_display_panel = workspace_controller.display_panels[0]  # display_panel will have changed now
            # document_controller.selected_display_panel = display_panel
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against old layout
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # now redo
            document_controller.handle_redo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against new layout
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_remove_from_splitter_with_three_items_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            document_controller.selected_display_panel = display_panel
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # remove display
            command = workspace_controller.remove_display_panel(display_panel)
            document_controller.push_undo_command(command)
            document_controller.selected_display_panel = display_panel
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # undo the remove
            document_controller.handle_undo()
            document_controller.selected_display_panel = workspace_controller.display_panels[0]  # display_panel will have changed now
            # document_controller.selected_display_panel = display_panel
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against old layout
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # now redo
            document_controller.handle_redo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against new layout
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_replace_display_panel_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            display_panel.set_display_panel_data_item(data_item)
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # change the display
            DisplayPanel.DisplayPanelManager().switch_to_display_content(document_controller, display_panel, "empty-display-panel")
            document_controller.selected_display_panel = workspace_controller.display_panels[0]  # display_panel will have changed now
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            self.assertNotEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # undo the remove
            document_controller.handle_undo()
            document_controller.selected_display_panel = workspace_controller.display_panels[0]  # display_panel will have changed now
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against old layout
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # now redo
            document_controller.handle_redo()
            # compare against new layout
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_swap_display_panel_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            display_panel2 = workspace_controller.display_panels[1]
            display_panel.set_display_panel_data_item(data_item)
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # change the display by dragging 2 into 1
            command = workspace_controller._replace_displayed_data_item(display_panel, None, display_panel2.save_contents())
            document_controller.push_undo_command(command)
            display_panel2._drag_finished(document_controller, "move")
            document_controller.selected_display_panel = workspace_controller.display_panels[0]  # display_panel will have changed now
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            self.assertNotEqual(old_workspace_layout, new_workspace_layout)
            self.assertEqual(old_workspace_layout["children"][0]["data_item_uuid"], new_workspace_layout["children"][1]["data_item_uuid"])
            self.assertIsNone(old_workspace_layout["children"][1].get("data_item_uuid"))
            self.assertIsNone(new_workspace_layout["children"][0].get("data_item_uuid"))
            # undo the remove
            document_controller.handle_undo()
            document_controller.selected_display_panel = workspace_controller.display_panels[1]  # display_panel will have changed now
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against old layout
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # now redo
            document_controller.handle_redo()
            document_controller.selected_display_panel = workspace_controller.display_panels[0]  # display_panel will have changed now
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against new layout
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_change_splitter_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            splitter_canvas_item = display_panel.container
            # save the original splits
            old_splits = splitter_canvas_item.splits
            # change the splits
            workspace_controller._splits_will_change(splitter_canvas_item)
            splitter_canvas_item.splits = [0.25, 0.75]
            workspace_controller._splits_did_change(splitter_canvas_item)
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # record the new splits
            new_splits = splitter_canvas_item.splits
            self.assertNotEqual(old_splits, new_splits)
            # undo the remove
            document_controller.handle_undo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against old layout
            self.assertEqual(old_splits, splitter_canvas_item.splits)
            # now redo
            document_controller.handle_redo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against new layout
            self.assertEqual(new_splits, splitter_canvas_item.splits)

    def test_create_workspace_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            # save info
            self.assertEqual(1, len(document_model.workspaces))
            old_workspace_layout = workspace_controller._workspace_layout
            # perform create command
            command = Workspace.Workspace.CreateWorkspaceCommand(workspace_controller, "NEW")
            command.perform()
            document_controller.push_undo_command(command)
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # check things
            self.assertEqual(2, len(document_model.workspaces))
            new_workspace_layout = workspace_controller._workspace_layout
            # undo
            document_controller.handle_undo()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # redo
            document_controller.handle_redo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_rename_workspace_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            # save info
            old_name = document_model.workspaces[0].name
            # perform command
            command = Workspace.Workspace.RenameWorkspaceCommand(workspace_controller, "NEW")
            command.perform()
            document_controller.push_undo_command(command)
            # check things
            self.assertEqual("NEW", document_model.workspaces[0].name)
            # undo
            document_controller.handle_undo()
            self.assertEqual(old_name, document_model.workspaces[0].name)
            # redo
            document_controller.handle_redo()
            self.assertEqual("NEW", document_model.workspaces[0].name)

    def test_remove_workspace_undo_and_redo_works_cleanly(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            # save info
            self.assertEqual(1, len(document_model.workspaces))
            old_workspace_layout = workspace_controller._workspace_layout
            # perform create command
            command = Workspace.Workspace.RemoveWorkspaceCommand(workspace_controller)
            command.perform()
            document_controller.push_undo_command(command)
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # check things
            self.assertEqual(0, len(document_model.workspaces))
            # undo
            document_controller.handle_undo()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # redo
            document_controller.handle_redo()
            self.assertEqual(0, len(document_model.workspaces))

    def test_workspace_records_and_reloads_image_panel_contents(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.FilePersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage, persistent_storage_system=memory_persistent_storage_system)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_1x1 = document_controller.document_model.workspaces[0]
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
        # reload
        document_model = DocumentModel.DocumentModel(library_storage=library_storage, persistent_storage_system=memory_persistent_storage_system)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_1x1 = document_controller.document_model.workspaces[0]
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, document_model.data_items[0])

    def __test_drop_on_1x1(self, region):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_data_item(data_item1)
            mime_data = MimeData("text/data_item_uuid", str(data_item2.uuid))
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, region, 160, 240)
            root_canvas_item.refresh_layout_immediate()
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the sizes were updated
            if region == "left" or region == "right":
                self.assertEqual(document_controller.workspace_controller.display_panels[0].canvas_rect.width, 320)
                self.assertEqual(document_controller.workspace_controller.display_panels[1].canvas_rect.width, 320)
            else:
                self.assertEqual(document_controller.workspace_controller.display_panels[0].canvas_rect.height, 240)
                self.assertEqual(document_controller.workspace_controller.display_panels[1].canvas_rect.height, 240)
            # check that the data items are in the right spot
            if region == "left" or region == "top":
                self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item2)
                self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item1)
            else:
                self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item1)
                self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item2)

    def test_workspace_mutates_when_new_item_dropped_on_edge_of_1x1_item(self):
        self.__test_drop_on_1x1("right")
        self.__test_drop_on_1x1("left")
        self.__test_drop_on_1x1("top")
        self.__test_drop_on_1x1("bottom")

    def test_drop_empty_on_1x1_top(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_data_item(data_item)
            mime_data = MimeData(DisplayPanel.DISPLAY_PANEL_MIME_TYPE, json.dumps({}))
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the data items are in the right spot
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, None)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_panel_type, "empty")
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item)

    def test_horizontal_browser_on_1x1_top(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_data_item(data_item)
            mime_data = MimeData(DisplayPanel.DISPLAY_PANEL_MIME_TYPE, json.dumps({"browser_type": "horizontal"}))
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the data items are in the right spot
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, None)
            self.assertEqual(document_controller.workspace_controller.display_panels[0]._display_panel_type, "horizontal")
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item)

    def test_grid_browser_on_1x1_top(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_data_item(data_item)
            mime_data = MimeData(DisplayPanel.DISPLAY_PANEL_MIME_TYPE, json.dumps({"browser_type": "grid"}))
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the data items are in the right spot
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, None)
            self.assertEqual(document_controller.workspace_controller.display_panels[0]._display_panel_type, "grid")
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item)

    def test_horizontal_browser_with_data_item_on_1x1_top(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_data_item(data_item)
            mime_data = MimeData(DisplayPanel.DISPLAY_PANEL_MIME_TYPE, json.dumps({"data_item_uuid": str(data_item.uuid), "browser_type": "horizontal"}))
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the data items are in the right spot
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item)
            self.assertEqual(document_controller.workspace_controller.display_panels[0]._display_panel_type, "horizontal")
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item)

    def test_workspace_splits_when_new_item_dropped_on_non_axis_edge_of_2x1_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item3 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item2)
            mime_data = MimeData("text/data_item_uuid", str(data_item3.uuid))
            display_panel = document_controller.workspace_controller.display_panels[0]
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "bottom", 160, 240)
            # check that there are now three image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 3)
            # check that there are still two top level image panels
            self.assertTrue(isinstance(root_canvas_item.canvas_items[0].canvas_items[0], CanvasItem.SplitterCanvasItem))
            self.assertEqual(len(root_canvas_item.canvas_items[0].canvas_items[0].canvas_items), 2)
            # check that the first top level item is a splitter and has two image panels
            self.assertTrue(isinstance(root_canvas_item.canvas_items[0].canvas_items[0], CanvasItem.SplitterCanvasItem))
            self.assertEqual(len(root_canvas_item.canvas_items[0].canvas_items[0].canvas_items), 2)
            # check that the sizes were updated
            root_canvas_item.refresh_layout_immediate()
            self.assertEqual(document_controller.workspace_controller.display_panels[0].canvas_rect.width, 320)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].canvas_rect.height, 240)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].canvas_rect.width, 320)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].canvas_rect.height, 240)
            self.assertEqual(document_controller.workspace_controller.display_panels[2].canvas_rect.width, 320)
            self.assertEqual(document_controller.workspace_controller.display_panels[2].canvas_rect.height, 480)

    def test_removing_left_item_in_2x1_results_in_a_single_top_level_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item2)
            display_panel = document_controller.workspace_controller.display_panels[0]
            document_controller.workspace_controller.remove_display_panel(display_panel)
            # check that there is now one image panel
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 1)
            # check that there is just one top level panel now
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item2)

    def test_removing_left_item_in_1x2x2_results_in_correct_layout(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("1x2x2"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item3 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item2)
            document_controller.workspace_controller.display_panels[2].set_displayed_data_item(data_item3)
            display_panel2 = document_controller.workspace_controller.display_panels[1]
            document_controller.workspace_controller.remove_display_panel(display_panel2)
            root_canvas_item.refresh_layout_immediate()
            self.assertEqual(document_controller.workspace_controller.display_panels[0].canvas_rect, Geometry.IntRect.from_tlbr(0, 0, 240, 640))
            self.assertEqual(document_controller.workspace_controller.display_panels[1].canvas_rect, Geometry.IntRect.from_tlbr(240, 0, 480, 640))

    def test_removing_middle_item_in_3x1_results_in_sensible_splits(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = { "type": "splitter", "orientation": "vertical", "splits": [0.5, 0.5], "children": [ { "type": "splitter", "orientation": "horizontal", "splits": [0.5, 0.5], "children": [ { "type": "image", "selected": True }, { "type": "image" } ] }, { "type": "image" } ] }
            workspace_3x1 = document_controller.workspace_controller.new_workspace("layout", d)
            document_controller.workspace_controller.change_workspace(workspace_3x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item3 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item2)
            document_controller.workspace_controller.display_panels[2].set_displayed_data_item(data_item3)
            display_panel = document_controller.workspace_controller.display_panels[1]
            splits = root_canvas_item.canvas_items[0].canvas_items[0].splits
            #logging.debug(document_controller.workspace_controller._deconstruct(root_canvas_item.canvas_items[0]))
            document_controller.workspace_controller.remove_display_panel(display_panel)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that there is just one top level panel now
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item1)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item3)
            # check that the splits are the same at the top level
            self.assertEqual(root_canvas_item.canvas_items[0].canvas_items[0].splits, splits)

    def test_close_button_in_header_works(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item2)
            root_canvas_item.refresh_layout_immediate()
            document_controller.workspace_controller.display_panels[0].header_canvas_item.simulate_click((12, 308))

    def test_dragging_header_to_swap_works(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item1)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item2)
            # simulate drag. data_item2 in right panel swaps with data_item1 in left panel.
            mime_data = self.app.ui.create_mime_data()
            mime_data.set_data_as_string("text/data_item_uuid", str(data_item2.uuid))
            document_controller.workspace_controller.handle_drop(document_controller.workspace_controller.display_panels[0], mime_data, "middle", 160, 240)
            document_controller.workspace_controller.display_panels[1]._drag_finished(document_controller, "move")
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item1)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display.container, data_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].display.container, data_item1)

    def test_clicking_in_header_selects_and_focuses_display_panel(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(data_item1)
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].request_focus()
            root_canvas_item.refresh_layout_immediate()
            self.assertTrue(document_controller.workspace_controller.display_panels[0].content_canvas_item.selected)
            self.assertTrue(document_controller.workspace_controller.display_panels[0].content_canvas_item.focused)
            # drag header. can't really test dragging without more test harness support. but make sure it gets this far.
            document_controller.workspace_controller.display_panels[1].header_canvas_item.simulate_click(Geometry.IntPoint(y=12, x=12))
            self.assertFalse(document_controller.workspace_controller.display_panels[0].content_canvas_item.selected)
            self.assertFalse(document_controller.workspace_controller.display_panels[0].content_canvas_item.focused)
            self.assertTrue(document_controller.workspace_controller.display_panels[1].content_canvas_item.selected)
            self.assertTrue(document_controller.workspace_controller.display_panels[1].content_canvas_item.focused)

    def test_creating_invalid_workspace_fails_gracefully(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_bad = document_controller.workspace_controller.new_workspace(layout={"type": "bad_component_type"})
            document_controller.workspace_controller.change_workspace(workspace_bad)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            panel_0_dict = document_controller.workspace_controller._deconstruct(root_canvas_item.canvas_items[0].canvas_items[0])
            panel_0_dict.pop("identifier")
            panel_0_dict.pop("uuid")
            self.assertEqual(panel_0_dict, {'selected': True, 'type': 'image'})

    def test_dropping_on_unfocused_display_panel_focuses(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_panel0 = document_controller.workspace_controller.display_panels[0]
            display_panel0.set_displayed_data_item(None)
            display_panel1 = document_controller.workspace_controller.display_panels[1]
            display_panel1.set_displayed_data_item(None)
            display_panel1.request_focus()
            # check assumptions
            self.assertFalse(display_panel0.content_canvas_item.focused)
            self.assertTrue(display_panel1.content_canvas_item.focused)
            # do drop
            mime_data = MimeData("text/data_item_uuid", str(data_item.uuid))
            document_controller.workspace_controller.handle_drop(display_panel0, mime_data, "middle", 160, 240)
            # check focus
            self.assertTrue(display_panel0.content_canvas_item.focused)
            self.assertFalse(display_panel1.content_canvas_item.focused)

    def test_browser_does_not_reset_selected_display_specifier_when_root_loses_focus(self):
        # make sure the inspector doesn't disappear when focus changes to one of its fields
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            d = {"type": "image", "display-panel-type": "browser-display-panel"}
            display_panel.change_display_panel_content(d)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            document_controller.periodic()
            self.assertIsNone(document_controller.focused_data_item)
            modifiers = CanvasItem.KeyboardModifiers()
            display_panel.root_container.canvas_widget.on_focus_changed(True)
            display_panel.root_container.canvas_widget.on_mouse_entered()
            display_panel.root_container.canvas_widget.on_mouse_pressed(40, 40, modifiers)
            display_panel.root_container.canvas_widget.on_mouse_released(40, 40, modifiers)
            self.assertIsNotNone(document_controller.focused_data_item)
            display_panel.root_container.canvas_widget.on_focus_changed(False)
            self.assertIsNotNone(document_controller.focused_data_item)

    class DisplayPanelController:
        def __init__(self, display_panel, error=False):
            self.type = "test" if not error else "error"
            self.__display_panel = display_panel
            self.__composition = CanvasItem.CanvasItemComposition()
            self.__composition.add_canvas_item(CanvasItem.TextButtonCanvasItem("ABC"))
            self.__display_panel.footer_canvas_item.insert_canvas_item(0, self.__composition)
            if error: raise RuntimeError()
            self.closed = False
        def close(self):
            self.__display_panel.footer_canvas_item.remove_canvas_item(self.__composition)
            self.__display_panel = None
            self.closed = True
        def save(self, d):
            pass

    class DisplayPanelControllerFactory:
        def __init__(self, match=None):
            self.priority = 1
            self._match = match
        def make_new(self, controller_type, display_panel, d):
            if controller_type == "test":
                return TestWorkspaceClass.DisplayPanelController(display_panel)
            if controller_type == "error":
                return TestWorkspaceClass.DisplayPanelController(display_panel, error=True)
            return None
        def match(self, document_model, data_item):
            if data_item == self._match:
                return {"controller_type": "test"}
            return None

    def test_drop_controlled_data_item_on_1x1_top_constructs_controller(self):
        data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory(data_item))
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            document_model.append_data_item(data_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            display_panel = document_controller.workspace_controller.display_panels[0]
            mime_data = MimeData("text/data_item_uuid", str(data_item.uuid))
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the data items are in the right spot
            self.assertEqual(document_controller.workspace_controller.display_panels[1].save_contents().get("display-panel-type"), None)  # uninitialized
            self.assertTrue(isinstance(document_controller.workspace_controller.display_panels[0]._display_panel_controller_for_test, TestWorkspaceClass.DisplayPanelController))
            # check that it closes properly too
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_switch_from_layout_with_controller_with_footer_works(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            workspace1 = document_controller.workspace_controller.new_workspace("1", {"type": "image", "display-panel-type": "data-display-panel", "controller_type": "test"})
            workspace2 = document_controller.workspace_controller.new_workspace("2", {"type": "image", "display-panel-type": "browser-display-panel"})
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            document_controller.workspace_controller.change_workspace(workspace1)
            document_controller.workspace_controller.change_workspace(workspace2)
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_closing_display_panel_with_display_controller_shuts_down_controller_correctly(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            d = {"type": "splitter", "orientation": "vertical", "splits": [0.5, 0.5], "children": [
                {"type": "image", "uuid": "0569ca31-afd7-48bd-ad54-5e2bb9f21102", "identifier": "a", "selected": True,
                    "display-panel-type": "data-display-panel", "controller_type": "test"},
                {"type": "image", "uuid": "acd77f9f-2f6f-4fbf-af5e-94330b73b997", "identifier": "b"}]}
            workspace1 = document_controller.workspace_controller.new_workspace("1", d)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            document_controller.workspace_controller.change_workspace(workspace1)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel_controller = display_panel._display_panel_controller_for_test
            self.assertFalse(display_panel_controller.closed)
            document_controller.workspace_controller.remove_display_panel(display_panel)
            self.assertTrue(display_panel_controller.closed)
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_switching_display_panel_with_display_controller_shuts_down_controller_correctly(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            workspace1 = document_controller.workspace_controller.new_workspace("1", {"type": "image", "display-panel-type": "data-display-panel", "controller_type": "test"})
            workspace2 = document_controller.workspace_controller.new_workspace("2", {"type": "image", "display-panel-type": "browser-display-panel"})
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            document_controller.workspace_controller.change_workspace(workspace1)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel_controller = display_panel._display_panel_controller_for_test
            self.assertFalse(display_panel_controller.closed)
            document_controller.workspace_controller.change_workspace(workspace2)
            self.assertTrue(display_panel_controller.closed)
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_switch_workspace_closes_display_panel_controller(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            workspace1 = document_controller.workspace_controller.new_workspace("1", {"type": "image", "display-panel-type": "data-display-panel", "controller_type": "test"})
            document_controller.workspace_controller.new_workspace("2", {"type": "image", "display-panel-type": "browser-display-panel"})
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            document_controller.workspace_controller.change_workspace(workspace1)
            display_panel_controller = document_controller.workspace_controller.display_panels[0]._display_panel_controller_for_test
            self.assertFalse(display_panel_controller.closed)
            document_controller.workspace_controller.change_to_previous_workspace()
            self.assertTrue(display_panel_controller.closed)
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_closing_data_item_display_after_closing_browser_detaches_browser_delegate(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            data_item1 = DataItem.DataItem(numpy.zeros((16, 16), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((16, 16), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].change_display_panel_content({"type": "image", "display-panel-type": "browser-display-panel"})
            document_controller.workspace_controller.display_panels[1].set_displayed_data_item(data_item1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))

    def test_restore_panel_like_drag_and_drop_closes_display_panel_controller(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            workspace1 = document_controller.workspace_controller.new_workspace("1", {"type": "image", "display-panel-type": "data-display-panel", "controller_type": "test"})
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            document_controller.workspace_controller.change_workspace(workspace1)
            display_panel = document_controller.workspace_controller.display_panels[0]
            self.assertTrue(isinstance(display_panel._display_panel_controller_for_test, TestWorkspaceClass.DisplayPanelController))
            display_panel_controller = display_panel._display_panel_controller_for_test
            self.assertFalse(display_panel_controller.closed)
            display_panel.change_display_panel_content({"type": "image"})
            self.assertIsNone(display_panel._display_panel_controller_for_test)
            self.assertTrue(display_panel_controller.closed)  # the old one
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_processing_puts_new_data_into_empty_display_panel_if_possible(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_displayed_data_item(source_data_item)
            document_controller.workspace_controller.display_panels[0].request_focus()
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, source_data_item)
            self.assertIsNone(document_controller.workspace_controller.display_panels[1].data_item)
            document_controller.processing_invert()
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, source_data_item)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, document_model.data_items[1])

    def test_data_display_panel_with_controller_not_treated_as_potential_result_panel(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            workspace = document_controller.workspace_controller.new_workspace("1", {"type": "image", "controller_type": "test"})
            document_controller.workspace_controller.change_workspace(workspace)
            self.assertIsNone(document_controller.next_result_display_panel())
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_reloading_display_panel_with_exception_keeps_workspace_layout_intact(self):
        DisplayPanel._test_log_exceptions = False
        try:
            DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("error", TestWorkspaceClass.DisplayPanelControllerFactory())
            library_storage = DocumentModel.MemoryPersistentStorage()
            document_model = DocumentModel.DocumentModel(library_storage=library_storage)
            document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
            # first create a workspace
            with contextlib.closing(document_controller):
                workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
                document_controller.workspace_controller.change_workspace(workspace_2x1)
            # modify it to include a controller which raises an exception during init
            library_storage_properties = library_storage.properties
            library_storage_properties["workspaces"][1]["layout"]["children"][0]["controller_type"] = "error"
            # create a new document based on the corrupt layout
            library_storage = DocumentModel.MemoryPersistentStorage(copy.deepcopy(library_storage_properties))
            document_model = DocumentModel.DocumentModel(library_storage=library_storage)
            document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
            with contextlib.closing(document_controller):
                pass
            # check to ensure that the exception didn't invalidate the entire layout
            self.assertEqual(2, len(library_storage.properties["workspaces"][1].get("layout", dict()).get("children", list())))
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("error")
        finally:
            DisplayPanel._test_log_exceptions = True


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
