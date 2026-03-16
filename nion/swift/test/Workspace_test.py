# standard libraries
import contextlib
import copy
import datetime
import json
import logging
import pathlib
import typing
import unittest
import urllib
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DisplayPanel
from nion.swift import DocumentController
from nion.swift import MimeTypes
from nion.swift import Workspace
from nion.swift.model import DataItem, DisplayItem
from nion.swift.test import DocumentController_test, TestContext
from nion.ui import CanvasItem
from nion.ui import Window
from nion.ui import TestUI
from nion.utils import DateTime
from nion.utils import Geometry


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


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
    elif layout_id == "6x1":
        d = {"type": "splitter", "orientation": "vertical", "splits": [1.0 / 6 for _ in range(6)],
             "children": [{"type": "image", "uuid": uuid1, "identifier": "a", "selected": True},
                          {"type": "image", "uuid": uuid2, "identifier": "b"},
                          {"type": "image", "uuid": uuid2, "identifier": "c"},
                          {"type": "image", "uuid": uuid4, "identifier": "d"},
                          {"type": "image", "uuid": uuid5, "identifier": "e"},
                          {"type": "image", "uuid": uuid6, "identifier": "f"}]}
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


class SplitCase:
    def __init__(self, selected_workspace_panels_indices: int | list[int], total_data_items: int, selected_data_items_indices: list[int] | None = None,
                 expected_split_shape: tuple[int, int] | None = None, total_expected_panels: int = 0,
                 workspace_data_items_indices: list[tuple[int, int]] | None = None, initial_layout_id: str = "1x1") \
            -> None:
        """Contains setup and the expected outcome for a specific split case testing the new workspace and split from selection functions.

        @param selected_workspace_panels_indices: either a single index or list of indices of the selected workspace panels used to set up a test.
        @param total_data_items: the total number of data items created for a test.
        @param selected_data_items_indices: indices of selected data panel items, None means no data items are selected.
        @param workspace_data_items_indices: data panels with data items used to set up the test, where the tuples are (index of display panel, index of data item in panel), None is when there are no data panels with items.
        @param initial_layout_id: a string identifier used by get_layout when setting up the initial workspace for a test.
        @param expected_split_shape: the expected split to be created, (horizontal, vertical), None is used when the test is disabled.
        @param total_expected_panels: the total number of panels expected in the workspace after a split.
        """
        self.selected_workspace_panels_indices = selected_workspace_panels_indices if isinstance(selected_workspace_panels_indices, list) else [selected_workspace_panels_indices]
        self.expected_h, self.expected_w = expected_split_shape if expected_split_shape else (0, 0)
        self.expected_split_shape: tuple[int, int] = expected_split_shape or (0, 0)
        self.total_expected_panels = total_expected_panels
        self.selected_data_items_indices: list[int] = selected_data_items_indices or []
        self.workspace_display_data_items_indices: list[tuple[int, int]] = workspace_data_items_indices or []
        self.initial_layout_id = initial_layout_id
        self.total_data_items = total_data_items
        if isinstance(selected_workspace_panels_indices, list):
            self.selected_panel_index = selected_workspace_panels_indices[0] if len(selected_workspace_panels_indices) > 0 else -1
        else:
            self.selected_panel_index = selected_workspace_panels_indices
        initial_shape_chars = initial_layout_id.split("x")
        original_shape = [int(value) for value in initial_shape_chars[:2]]
        assert len(original_shape) == 2
        self.initial_shape = tuple(original_shape)


class TestWorkspaceClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_basic_change_layout_results_in_correct_image_panel_count(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            DocumentController_test.construct_test_document(document_controller)
            workspace_1x1 = document_controller.project.workspaces[0]
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            workspace_3x1 = document_controller.workspace_controller.new_workspace(*get_layout("3x1"))
            workspace_2x2 = document_controller.workspace_controller.new_workspace(*get_layout("2x2"))
            workspace_3x2 = document_controller.workspace_controller.new_workspace(*get_layout("3x2"))
            workspace_1x2 = document_controller.workspace_controller.new_workspace(*get_layout("1x2"))
            self.assertEqual(len(document_controller.project.workspaces), 6)
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            workspace_1x1 = document_controller.project.workspaces[0]
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            image_panel_weak_ref = weakref.ref(document_controller.workspace_controller.display_panels[0])
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            self.assertIsNone(image_panel_weak_ref())

    def test_image_panel_focused_when_clicked(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.workspace_controller.display_panels[1].set_display_item(document_model.get_display_item_for_data_item(data_item2))
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
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

    def test_image_panel_allows_secondary_selections(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_3x1 = document_controller.workspace_controller.new_workspace(*get_layout("3x1"))
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item3 = DataItem.DataItem(numpy.zeros((8,)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            document_controller.workspace_controller.change_workspace(workspace_3x1)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.workspace_controller.display_panels[1].set_display_item(document_model.get_display_item_for_data_item(data_item2))
            document_controller.workspace_controller.display_panels[2].set_display_item(document_model.get_display_item_for_data_item(data_item3))
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # click in first panel
            root_canvas_item.canvas_widget.simulate_mouse_click(110, 240, CanvasItem.KeyboardModifiers())
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[0])
            self.assertEqual(0, len(document_controller.secondary_display_panels))
            # now click the second panel with control
            root_canvas_item.canvas_widget.simulate_mouse_click(330, 240, CanvasItem.KeyboardModifiers(control=True))
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[0])
            self.assertEqual(document_controller.workspace_controller.display_panels[1:2], list(document_controller.secondary_display_panels))
            # now click the third panel with control
            root_canvas_item.canvas_widget.simulate_mouse_click(550, 240, CanvasItem.KeyboardModifiers(control=True))
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[0])
            self.assertEqual(document_controller.workspace_controller.display_panels[1:3], list(document_controller.secondary_display_panels))
            # now click the second panel (image) then add other panels and click primary and ensure only it is selected
            root_canvas_item.canvas_widget.simulate_mouse_click(330, 240, CanvasItem.KeyboardModifiers())
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[1])
            self.assertEqual(0, len(document_controller.secondary_display_panels))
            root_canvas_item.canvas_widget.simulate_mouse_click(110, 240, CanvasItem.KeyboardModifiers(control=True))
            root_canvas_item.canvas_widget.simulate_mouse_click(550, 240, CanvasItem.KeyboardModifiers(control=True))
            self.assertEqual(2, len(document_controller.secondary_display_panels))
            root_canvas_item.canvas_widget.simulate_mouse_click(330, 240, CanvasItem.KeyboardModifiers())
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[1])
            self.assertEqual(0, len(document_controller.secondary_display_panels))
            # now click the third panel (line plot) then add other panels and click primary and ensure only it is selected
            root_canvas_item.canvas_widget.simulate_mouse_click(550, 240, CanvasItem.KeyboardModifiers())
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[2])
            self.assertEqual(0, len(document_controller.secondary_display_panels))
            root_canvas_item.canvas_widget.simulate_mouse_click(110, 240, CanvasItem.KeyboardModifiers(control=True))
            root_canvas_item.canvas_widget.simulate_mouse_click(330, 240, CanvasItem.KeyboardModifiers(control=True))
            self.assertEqual(2, len(document_controller.secondary_display_panels))
            root_canvas_item.canvas_widget.simulate_mouse_click(550, 240, CanvasItem.KeyboardModifiers())
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[2])
            self.assertEqual(0, len(document_controller.secondary_display_panels))

    def test_image_panel_deselects_multiple_empty_panels(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            workspace_3x1 = document_controller.workspace_controller.new_workspace(*get_layout("3x1"))
            document_controller.workspace_controller.change_workspace(workspace_3x1)
            document_controller.workspace_controller.display_panels[0].set_display_item(None)
            document_controller.workspace_controller.display_panels[1].set_display_item(None)
            document_controller.workspace_controller.display_panels[2].set_display_item(None)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # click in first panel
            root_canvas_item.canvas_widget.simulate_mouse_click(110, 240, CanvasItem.KeyboardModifiers())
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[0])
            self.assertEqual(0, len(document_controller.secondary_display_panels))
            # now click the second panel with control
            root_canvas_item.canvas_widget.simulate_mouse_click(330, 240, CanvasItem.KeyboardModifiers(control=True))
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[0])
            self.assertEqual(document_controller.workspace_controller.display_panels[1:2], list(document_controller.secondary_display_panels))
            # now click the second panel and make sure other panel gets deselected
            root_canvas_item.canvas_widget.simulate_mouse_click(330, 240, CanvasItem.KeyboardModifiers())
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[1])
            self.assertEqual(0, len(document_controller.secondary_display_panels))
            # reselect first and second panels
            # now click in the first panel and make sure other panel gets deselected
            root_canvas_item.canvas_widget.simulate_mouse_click(110, 240, CanvasItem.KeyboardModifiers())
            root_canvas_item.canvas_widget.simulate_mouse_click(330, 240, CanvasItem.KeyboardModifiers(control=True))
            root_canvas_item.canvas_widget.simulate_mouse_click(110, 240, CanvasItem.KeyboardModifiers())
            self.assertTrue(document_controller.selected_display_panel, document_controller.workspace_controller.display_panels[0])
            self.assertEqual(0, len(document_controller.secondary_display_panels))

    def test_workspace_construct_and_deconstruct_result_in_matching_descriptions(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # deconstruct
            desc1 = get_layout("2x1")[1]
            desc2 = document_controller.workspace_controller._deconstruct(root_canvas_item.canvas_items[0].canvas_items[0])
            self.assertEqual(desc1, desc2)

    def test_workspace_change_records_workspace_uuid(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            DocumentController_test.construct_test_document(document_controller)
            workspace_1x1 = document_controller.project.workspaces[0]
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            self.assertEqual(document_controller.project.workspace_uuid, workspace_1x1.uuid)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            self.assertEqual(document_controller.project.workspace_uuid, workspace_2x1.uuid)
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            self.assertEqual(document_controller.project.workspace_uuid, workspace_1x1.uuid)

    def test_workspace_change_records_workspace_data_item_contents(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_1x1 = document_controller.project.workspaces[0]
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item3 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item2))
            document_controller.workspace_controller.display_panels[1].set_display_item(document_model.get_display_item_for_data_item(data_item3))
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item1)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item3)

    def test_workspace_records_json_compatible_content_when_closing_document(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                workspace_1x1 = document_controller.project.workspaces[0]
                data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
                document_model.append_data_item(data_item1)
                document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            json_str = json.dumps(profile_context.project_properties["workspaces"])
            properties = json.loads(json_str)
            self.assertEqual(properties, profile_context.project_properties["workspaces"])

    def test_workspace_saves_contents_immediately_following_change(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
                root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
                workspace_controller = document_controller.workspace_controller
                display_panel = workspace_controller.display_panels[0]
                workspace_controller.insert_display_panel(display_panel, "bottom")
                # copy the profile properties before the document closes
                profile_properties = copy.deepcopy(profile_context.profile_properties)
            profile_context.profile_properties = profile_properties
            # reload with the storage copied before the document closes
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                workspace_controller = document_controller.workspace_controller
                self.assertEqual(2, len(workspace_controller.display_panels))

    def test_workspace_saves_contents_immediately_following_adjustment(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
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
            # reload with the storage copied before the document closes
            document_controller = profile_context.create_document_controller(auto_close=False)
            with contextlib.closing(document_controller):
                workspace_controller = document_controller.workspace_controller
                display_panel = workspace_controller.display_panels[0]
                root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
                root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
                self.assertEqual([0.4, 0.6], display_panel.container.splits)

    def test_workspace_saves_contents_immediately_following_controller_change(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        try:
            with create_memory_profile_context() as profile_context:
                document_controller = profile_context.create_document_controller(auto_close=False)
                document_model = document_controller.document_model
                with contextlib.closing(document_controller):
                    workspace_controller = document_controller.workspace_controller
                    root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
                    root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
                    display_panel = workspace_controller.display_panels[0]
                    d = {"type": "image", "controller_type": "test"}
                    display_panel.change_display_panel_content(d)
                # reload with the storage copied before the document closes
                document_controller = profile_context.create_document_controller(auto_close=False)
                document_model = document_controller.document_model
                with contextlib.closing(document_controller):
                    workspace_controller = document_controller.workspace_controller
                    display_panel = workspace_controller.display_panels[0]
                    root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
                    root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
                    self.assertEqual("test", display_panel.save_contents()["controller_type"])
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_workspace_saves_contents_immediately_following_view_change(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                workspace_controller = document_controller.workspace_controller
                root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
                root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
                display_panel = workspace_controller.display_panels[0]
                d = {"type": "image", "display-panel-type": "browser-display-panel"}
                display_panel.change_display_panel_content(d)
            # reload with the storage copied before the document closes
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                workspace_controller = document_controller.workspace_controller
                display_panel = workspace_controller.display_panels[0]
                root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
                root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
                self.assertEqual("grid", display_panel.save_contents()["browser_type"])

    def test_workspace_insert_into_no_splitter_undo_and_redo_works_cleanly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # insert a new display
            command = workspace_controller.insert_display_panel(display_panel, "bottom")
            document_controller.push_undo_command(command)
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # undo the insert
            document_controller.handle_undo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against old layout
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # now redo
            document_controller.handle_redo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against new layout
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_insert_into_splitter_undo_and_redo_works_cleanly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # undo the insert
            document_controller.handle_undo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against old layout
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # now redo
            document_controller.handle_redo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against new layout
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_remove_from_splitter_with_two_items_undo_and_redo_works_cleanly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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

    def test_workspace_updates_layout_after_creation(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((12, 12))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((12, 12))))
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            document_controller.selected_display_panel = display_panel
            document_controller.perform_action("workspace.split_horizontal")
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # put the data items in the workspace display panels
            workspace_controller.display_panels[0].set_display_panel_display_item(document_model.get_display_item_for_data_item(document_model.data_items[0]))
            workspace_controller.display_panels[1].set_display_panel_display_item(document_model.get_display_item_for_data_item(document_model.data_items[1]))
            # confirm they are there
            self.assertEqual(document_model.data_items[0], workspace_controller.display_panels[0].data_item)
            self.assertEqual(document_model.data_items[1], workspace_controller.display_panels[1].data_item)
            # now create a new workspace, switch to it, then switch back to the original
            workspace_0 = document_controller.project.workspaces[0]
            workspace_1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_1)
            document_controller.workspace_controller.change_workspace(workspace_0)
            # confirm the data items are still in the workspace display panels
            self.assertEqual(document_model.data_items[0], workspace_controller.display_panels[0].data_item)
            self.assertEqual(document_model.data_items[1], workspace_controller.display_panels[1].data_item)

    def test_workspace_remove_bottom_two_in_2x2_undo_and_redo_works_cleanly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            document_controller.selected_display_panel = display_panel
            document_controller.perform_action("workspace.split_2x2")
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # remove display
            workspace_controller.close_display_panels(workspace_controller.display_panels[2:4])
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # undo the remove
            document_controller.handle_undo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against old layout
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # now redo
            document_controller.handle_redo()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # compare against new layout
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_split_multiple_panels(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            workspace_controller = document_controller.workspace_controller
            self.assertEqual(1, len(workspace_controller.display_panels))
            document_controller.selected_display_panel = workspace_controller.display_panels[0]
            document_controller.perform_action("workspace.split_2x2")
            self.assertEqual(4, len(workspace_controller.display_panels))
            document_controller.selected_display_panel = workspace_controller.display_panels[0]
            document_controller.add_secondary_display_panel(workspace_controller.display_panels[1])
            document_controller.perform_action("workspace.split_vertical")
            self.assertEqual(6, len(workspace_controller.display_panels))

    def test_workspace_split_with_another_panel_focused(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            workspace_controller = document_controller.workspace_controller
            self.assertEqual(1, len(workspace_controller.display_panels))
            document_controller.selected_display_panel = workspace_controller.display_panels[0]
            document_controller.perform_action("workspace.split_horizontal")
            document_controller.selected_display_panel = workspace_controller.display_panels[1]
            action_context = document_controller._get_action_context_for_display_items(document_controller.selected_display_items, workspace_controller.display_panels[0])
            document_controller.perform_action_in_context("workspace.split_vertical", action_context)

    def test_workspace_split_with_another_no_panel_focused(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            workspace_controller = document_controller.workspace_controller
            self.assertEqual(1, len(workspace_controller.display_panels))
            document_controller.selected_display_panel = None
            action_context = document_controller._get_action_context_for_display_items(document_controller.selected_display_items, workspace_controller.display_panels[0])
            document_controller.perform_action_in_context("workspace.split_vertical", action_context)

    def test_workspace_split_horizontal_does_not_create_extra_splits(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            workspace_controller = document_controller.workspace_controller
            self.assertEqual(1, len(workspace_controller.display_panels))
            document_controller.selected_display_panel = workspace_controller.display_panels[0]
            document_controller.perform_action("workspace.split_horizontal")
            self.assertEqual(1, len(workspace_controller._canvas_item.canvas_items))
            self.assertIsInstance(workspace_controller._canvas_item.canvas_items[0], CanvasItem.SplitterCanvasItem)
            self.assertEqual(2, len(workspace_controller._canvas_item.canvas_items[0].canvas_items))
            self.assertIsInstance(workspace_controller._canvas_item.canvas_items[0].canvas_items[0], DisplayPanel.DisplayPanel)
            self.assertIsInstance(workspace_controller._canvas_item.canvas_items[0].canvas_items[1], DisplayPanel.DisplayPanel)

    def test_workspace_change_workspace_to_data_thumbnail_grid_works(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            document_controller.workspace_controller.switch_to_display_content(display_panel, "data-display-panel", display_item)
            document_controller.workspace_controller.switch_to_display_content(display_panel, "browser-display-panel")
            document_controller.workspace_controller.switch_to_display_content(display_panel, "thumbnail-browser-display-panel")
            document_controller.workspace_controller.switch_to_display_content(display_panel, "empty-display-panel")

    def test_workspace_change_workspace_undo_redo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            document_controller.workspace_controller.switch_to_display_content(display_panel, "empty-display-panel")
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.handle_undo()
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            document_controller.handle_redo()
            document_controller.handle_undo()
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)

    def test_workspace_replace_display_panel_undo_and_redo_works_cleanly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            display_panel.set_display_panel_display_item(display_item)
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # change the display
            document_controller.workspace_controller.switch_to_display_content(display_panel, "empty-display-panel")
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            display_panel2 = workspace_controller.display_panels[1]
            display_panel.set_display_panel_display_item(display_item)
            # save the original layout
            old_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            # change the display by dragging 2 into 1
            document_controller.replaced_display_panel_content_flag = True  # this would get set by the drag command
            command = workspace_controller._replace_displayed_display_item(display_panel, None, display_panel2.save_contents())
            document_controller.push_undo_command(command)
            display_panel2._drag_finished(document_controller, "move")
            document_controller.selected_display_panel = workspace_controller.display_panels[0]  # display_panel will have changed now
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # record the new layout
            new_workspace_layout = copy.deepcopy(workspace_controller._workspace_layout)
            self.assertNotEqual(old_workspace_layout, new_workspace_layout)
            self.assertEqual(old_workspace_layout["children"][0]["display_item_specifier"], new_workspace_layout["children"][1]["display_item_specifier"])
            self.assertIsNone(old_workspace_layout["children"][1].get("display_item_specifier"))
            self.assertIsNone(new_workspace_layout["children"][0].get("display_item_specifier"))
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            # save info
            self.assertEqual(1, len(document_controller.project.workspaces))
            old_workspace_uuid = document_controller.workspace_controller._workspace.uuid
            old_workspace_layout = workspace_controller._workspace_layout
            # perform create command
            command = Workspace.CreateWorkspaceCommand(workspace_controller, "NEW")
            command.perform()
            document_controller.push_undo_command(command)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # check things
            self.assertEqual(2, len(document_controller.project.workspaces))
            new_workspace_layout = workspace_controller._workspace_layout
            # undo
            document_controller.handle_undo()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            self.assertEqual(1, len(document_controller.project.workspaces))
            self.assertEqual(old_workspace_uuid, document_controller.workspace_controller._workspace.uuid)
            # redo
            document_controller.handle_redo()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)
            self.assertEqual(2, len(document_controller.project.workspaces))

    def test_rename_workspace_undo_and_redo_works_cleanly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            # save info
            old_name = document_controller.project.workspaces[0].name
            # perform command
            command = Workspace.RenameWorkspaceCommand(workspace_controller, "NEW")
            command.perform()
            document_controller.push_undo_command(command)
            # check things
            self.assertEqual("NEW", document_controller.project.workspaces[0].name)
            # undo
            document_controller.handle_undo()
            self.assertEqual(old_name, document_controller.project.workspaces[0].name)
            # redo
            document_controller.handle_redo()
            self.assertEqual("NEW", document_controller.project.workspaces[0].name)

    def test_remove_workspace_undo_and_redo_works_cleanly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            # perform create command
            command = Workspace.CreateWorkspaceCommand(workspace_controller, "NEW")
            command.perform()
            document_controller.push_undo_command(command)
            # save info
            self.assertEqual(2, len(document_controller.project.workspaces))
            old_workspace_layout = workspace_controller._workspace_layout
            # perform remove command
            command = Workspace.RemoveWorkspaceCommand(workspace_controller)
            command.perform()
            document_controller.push_undo_command(command)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # check things
            self.assertEqual(1, len(document_controller.project.workspaces))
            # undo
            document_controller.handle_undo()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            # redo
            document_controller.handle_redo()
            self.assertEqual(1, len(document_controller.project.workspaces))

    def test_clone_workspace_undo_and_redo_works_cleanly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            workspace_controller.insert_display_panel(display_panel, "bottom").close()
            # save info
            self.assertEqual(1, len(document_controller.project.workspaces))
            old_workspace_uuid = document_controller.workspace_controller._workspace.uuid
            old_workspace_layout = workspace_controller._workspace_layout
            # perform create command
            command = Workspace.CloneWorkspaceCommand(workspace_controller, "NEW")
            command.perform()
            document_controller.push_undo_command(command)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            # check things
            self.assertEqual(2, len(document_controller.project.workspaces))
            # TODO: why is splitter incorrect? check children.
            self.assertEqual(old_workspace_layout["children"], workspace_controller._workspace_layout["children"])
            new_workspace_layout = workspace_controller._workspace_layout
            # undo
            document_controller.handle_undo()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual(old_workspace_layout, workspace_controller._workspace_layout)
            self.assertEqual(1, len(document_controller.project.workspaces))
            self.assertEqual(old_workspace_uuid, document_controller.workspace_controller._workspace.uuid)
            # redo
            document_controller.handle_redo()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual(new_workspace_layout, workspace_controller._workspace_layout)
            self.assertEqual(2, len(document_controller.project.workspaces))

    def test_remove_workspace_enables_next_most_recent_workspace(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            # create three workspaces
            workspace_controller = document_controller.workspace_controller
            workspace1 = workspace_controller._workspace
            workspace2 = workspace_controller.new_workspace(*get_layout("2x1"))
            workspace3 = workspace_controller.new_workspace(*get_layout("2x1"))
            workspace1.name = "1"
            utcnow = DateTime.utcnow()
            workspace1._set_created(utcnow + datetime.timedelta(seconds=2))
            workspace2.name = "2"
            workspace2._set_created(utcnow + datetime.timedelta(seconds=1))
            workspace3.name = "3"
            workspace3._set_created(utcnow + datetime.timedelta(seconds=3))
            # needs to fail here, sorted order needs to be different from added order
            self.assertEqual(["3", "1", "2"], [w.name for w in document_controller.project.sorted_workspaces])
            workspace_controller.change_workspace(workspace3)
            self.assertEqual(3, len(document_controller.project.workspaces))
            # perform remove command
            command = Workspace.RemoveWorkspaceCommand(workspace_controller)
            command.perform()
            document_controller.push_undo_command(command)
            # check things
            self.assertEqual(2, len(document_controller.project.workspaces))
            self.assertEqual("1", workspace_controller._workspace.name)

    def test_workspace_records_and_reloads_image_panel_contents(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                workspace_1x1 = document_controller.project.workspaces[0]
                data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
                document_model.append_data_item(data_item1)
                document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            # reload
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                workspace_1x1 = document_controller.project.workspaces[0]
                self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, document_model.data_items[0])

    def __test_drop_on_1x1(self, region):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_display_item(display_item1)
            mime_data = TestUI.MimeData()
            MimeTypes.mime_data_put_display_item(mime_data, display_item2)
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
                self.assertEqual(document_controller.workspace_controller.display_panels[0].display_item, display_item2)
                self.assertEqual(document_controller.workspace_controller.display_panels[1].display_item, display_item1)
            else:
                self.assertEqual(document_controller.workspace_controller.display_panels[0].display_item, display_item1)
                self.assertEqual(document_controller.workspace_controller.display_panels[1].display_item, display_item2)

    def test_workspace_mutates_when_new_item_dropped_on_edge_of_1x1_item(self):
        self.__test_drop_on_1x1("right")
        self.__test_drop_on_1x1("left")
        self.__test_drop_on_1x1("top")
        self.__test_drop_on_1x1("bottom")

    def test_drop_empty_on_1x1_top(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_display_item(display_item)
            mime_data = TestUI.MimeData()
            MimeTypes.mime_data_put_panel(mime_data, None, {})
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the data items are in the right spot
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, None)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_panel_type, "empty")
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item)

    def test_horizontal_browser_on_1x1_top(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_display_item(display_item)
            mime_data = TestUI.MimeData()
            MimeTypes.mime_data_put_panel(mime_data, None, {"browser_type": "horizontal"})
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the data items are in the right spot
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, None)
            self.assertEqual(document_controller.workspace_controller.display_panels[0]._display_panel_type, "horizontal")
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item)

    def test_grid_browser_on_1x1_top(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_display_item(display_item)
            mime_data = TestUI.MimeData()
            MimeTypes.mime_data_put_panel(mime_data, None, {"browser_type": "grid"})
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the data items are in the right spot
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, None)
            self.assertEqual(document_controller.workspace_controller.display_panels[0]._display_panel_type, "grid")
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, data_item)

    def test_horizontal_browser_with_data_item_on_1x1_top(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_display_item(display_item)
            mime_data = TestUI.MimeData()
            MimeTypes.mime_data_put_panel(mime_data, display_item, {"browser_type": "horizontal"})
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
            # check that there are now two image panels
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
            # check that the data items are in the right spot
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_item, display_item)
            self.assertEqual(document_controller.workspace_controller.display_panels[0]._display_panel_type, "horizontal")
            self.assertEqual(document_controller.workspace_controller.display_panels[1].display_item, display_item)

    def test_workspace_splits_when_new_item_dropped_on_non_axis_edge_of_2x1_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            display_item3 = document_model.get_display_item_for_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_display_item(display_item1)
            document_controller.workspace_controller.display_panels[1].set_display_item(display_item2)
            mime_data = TestUI.MimeData()
            MimeTypes.mime_data_put_display_item(mime_data, display_item3)
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.workspace_controller.display_panels[1].set_display_item(document_model.get_display_item_for_data_item(data_item2))
            display_panel = document_controller.workspace_controller.display_panels[0]
            document_controller.workspace_controller.remove_display_panel(display_panel)
            # check that there is now one image panel
            self.assertEqual(len(document_controller.workspace_controller.display_panels), 1)
            # check that there is just one top level panel now
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item2)

    def test_removing_left_item_in_1x2x2_results_in_correct_layout(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.workspace_controller.display_panels[1].set_display_item(document_model.get_display_item_for_data_item(data_item2))
            document_controller.workspace_controller.display_panels[2].set_display_item(document_model.get_display_item_for_data_item(data_item3))
            display_panel2 = document_controller.workspace_controller.display_panels[1]
            document_controller.workspace_controller.remove_display_panel(display_panel2)
            root_canvas_item.refresh_layout_immediate()
            self.assertEqual(document_controller.workspace_controller.display_panels[0].canvas_rect, Geometry.IntRect.from_tlbr(0, 0, 240, 640))
            self.assertEqual(document_controller.workspace_controller.display_panels[1].canvas_rect, Geometry.IntRect.from_tlbr(240, 0, 480, 640))

    def test_removing_middle_item_in_3x1_results_in_sensible_splits(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.workspace_controller.display_panels[1].set_display_item(document_model.get_display_item_for_data_item(data_item2))
            document_controller.workspace_controller.display_panels[2].set_display_item(document_model.get_display_item_for_data_item(data_item3))
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.workspace_controller.display_panels[1].set_display_item(document_model.get_display_item_for_data_item(data_item2))
            root_canvas_item.refresh_layout_immediate()
            document_controller.workspace_controller.display_panels[0].header_canvas_item.simulate_click((12, 308))

    def test_dragging_header_to_swap_works(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_display_item(display_item1)
            document_controller.workspace_controller.display_panels[1].set_display_item(display_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_item, display_item1)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].display_item, display_item2)
            # simulate drag. data_item2 in right panel swaps with data_item1 in left panel.
            mime_data = self._test_setup.app.ui.create_mime_data()
            MimeTypes.mime_data_put_display_item(mime_data, display_item2)
            document_controller.replaced_display_panel_content_flag = True  # this would get set by the drag command
            document_controller.workspace_controller.handle_drop(document_controller.workspace_controller.display_panels[0], mime_data, "middle", 160, 240)
            document_controller.workspace_controller.display_panels[1]._drag_finished(document_controller, "move")
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_item, display_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].display_item, display_item1)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_item.data_item, data_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].display_item.data_item, data_item1)

    def test_display_panel_selection_updates_properly_with_data_panel_filter(self):
        # this tests a failure where 2nd processing action would replace the source display item with something else.
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_controller.display_items_model._ttt = "ONE"
            document_controller.filtered_display_items_model._ttt = "TWO"
            document_model = document_controller.document_model
            workspace_2x2 = document_controller.workspace_controller.new_workspace(*get_layout("2x2"))
            document_controller.workspace_controller.change_workspace(workspace_2x2)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item1.title = "aaa"
            data_item2.title = "bbb"
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_display_item(display_item2)
            document_controller.workspace_controller.display_panels[0].request_focus()
            # error only occurred with filter enabled
            document_controller.filter_controller.text_filter_changed("bbb")
            self.assertEqual(2, len(document_model.display_items))
            document_controller.perform_action(DocumentController.GaussianFilterAction())
            self.assertEqual(3, len(document_model.display_items))
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_item, display_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].display_item, document_model.display_items[2])
            document_controller.workspace_controller.display_panels[1].request_focus()
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_item, display_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].display_item, document_model.display_items[2])
            document_controller.perform_action(DocumentController.FFTAction())
            self.assertEqual(4, len(document_model.display_items))
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_item, display_item2)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].display_item, document_model.display_items[2])
            self.assertEqual(document_controller.workspace_controller.display_panels[2].display_item, document_model.display_items[3])

    def test_clicking_in_header_selects_and_focuses_display_panel(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.workspace_controller.display_panels[1].set_display_item(document_model.get_display_item_for_data_item(data_item2))
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_bad = document_controller.workspace_controller.new_workspace(layout={"type": "bad_component_type"})
            document_controller.workspace_controller.change_workspace(workspace_bad)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            panel_0_dict = document_controller.workspace_controller._deconstruct(root_canvas_item.canvas_items[0].canvas_items[0])
            panel_0_dict.pop("identifier")
            panel_0_dict.pop("uuid")
            self.assertEqual(panel_0_dict, {'selected': True, 'type': 'image'})

    def test_dropping_on_unfocused_display_panel_focuses(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel0 = document_controller.workspace_controller.display_panels[0]
            display_panel0.set_display_item(None)
            display_panel1 = document_controller.workspace_controller.display_panels[1]
            display_panel1.set_display_item(None)
            display_panel1.request_focus()
            # check assumptions
            self.assertFalse(display_panel0.content_canvas_item.focused)
            self.assertTrue(display_panel1.content_canvas_item.focused)
            # do drop
            mime_data = TestUI.MimeData()
            MimeTypes.mime_data_put_display_item(mime_data, display_item)
            document_controller.workspace_controller.handle_drop(display_panel0, mime_data, "middle", 160, 240)
            # check focus
            self.assertTrue(display_panel0.content_canvas_item.focused)
            self.assertFalse(display_panel1.content_canvas_item.focused)

    def test_browser_does_not_reset_selected_display_item_when_root_loses_focus(self):
        # make sure the inspector doesn't disappear when focus changes to one of its fields
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            d = {"type": "image", "display-panel-type": "browser-display-panel"}
            display_panel.change_display_panel_content(d)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            document_controller.periodic()
            self.assertIsNone(document_controller.selected_data_item)
            modifiers = CanvasItem.KeyboardModifiers()
            display_panel.root_container.canvas_widget.on_focus_changed(True)
            display_panel.root_container.canvas_widget.on_mouse_entered()
            display_panel.root_container.canvas_widget.on_mouse_pressed(40, 40, modifiers)
            display_panel.root_container.canvas_widget.on_mouse_released(40, 40, modifiers)
            self.assertIsNotNone(document_controller.selected_data_item)
            display_panel.root_container.canvas_widget.on_focus_changed(False)
            self.assertIsNotNone(document_controller.selected_data_item)

    class DisplayPanelController:
        def __init__(self, display_panel, data_item, error=False):
            self.type = "test" if not error else "error"
            self.__display_panel = display_panel
            self.__composition = CanvasItem.CanvasItemComposition()
            self.__composition.add_canvas_item(CanvasItem.TextButtonCanvasItem("ABC"))
            self.__display_panel.footer_canvas_item.insert_canvas_item(0, self.__composition)
            display_panel.set_display_item(display_panel.document_controller.document_model.get_display_item_for_data_item(data_item))
            if error: raise RuntimeError()
            self.closed = False
        def close(self) -> None:
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
                return TestWorkspaceClass.DisplayPanelController(display_panel, self._match)
            if controller_type == "error":
                return TestWorkspaceClass.DisplayPanelController(display_panel, self._match, error=True)
            return None
        def match(self, document_model, data_item):
            if data_item == self._match:
                return {"controller_type": "test"}
            return None

    def test_drop_controlled_data_item_on_1x1_top_constructs_controller(self):
        data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory(data_item))
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
                root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
                display_panel = document_controller.workspace_controller.display_panels[0]
                mime_data = TestUI.MimeData()
                MimeTypes.mime_data_put_display_item(mime_data, display_item)
                document_controller.workspace_controller.handle_drop(display_panel, mime_data, "top", 160, 240)
                # check that there are now two image panels
                self.assertEqual(len(document_controller.workspace_controller.display_panels), 2)
                # check that the data items are in the right spot
                self.assertEqual(document_controller.workspace_controller.display_panels[1].save_contents().get("display-panel-type"), None)  # uninitialized
                self.assertTrue(isinstance(document_controller.workspace_controller.display_panels[0]._display_panel_controller_for_test, TestWorkspaceClass.DisplayPanelController))
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_switch_from_layout_with_controller_with_footer_works(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
                data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
                document_model.append_data_item(data_item)
                workspace1 = document_controller.workspace_controller.new_workspace("1", {"type": "image", "display-panel-type": "data-display-panel", "controller_type": "test"})
                workspace2 = document_controller.workspace_controller.new_workspace("2", {"type": "image", "display-panel-type": "browser-display-panel"})
                root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
                root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
                document_controller.workspace_controller.change_workspace(workspace1)
                document_controller.workspace_controller.change_workspace(workspace2)
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_closing_display_panel_with_display_controller_shuts_down_controller_correctly(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
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
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_switching_display_panel_with_display_controller_shuts_down_controller_correctly(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
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
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_switch_workspace_closes_display_panel_controller(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
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
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_closing_data_item_display_after_closing_browser_detaches_browser_delegate(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            data_item1 = DataItem.DataItem(numpy.zeros((16, 16), numpy.double))
            data_item2 = DataItem.DataItem(numpy.zeros((16, 16), numpy.double))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_controller.workspace_controller.display_panels[0].change_display_panel_content({"type": "image", "display-panel-type": "browser-display-panel"})
            document_controller.workspace_controller.display_panels[1].set_display_item(document_model.get_display_item_for_data_item(data_item1))
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))

    def test_restore_panel_like_drag_and_drop_closes_display_panel_controller(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
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
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_processing_puts_new_data_into_empty_display_panel_if_possible(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float32))
            document_model.append_data_item(source_data_item)
            workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            document_controller.workspace_controller.display_panels[0].set_display_item(document_model.get_display_item_for_data_item(source_data_item))
            document_controller.workspace_controller.display_panels[0].request_focus()
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, source_data_item)
            self.assertIsNone(document_controller.workspace_controller.display_panels[1].data_item)
            document_controller.processing_invert()
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, source_data_item)
            self.assertEqual(document_controller.workspace_controller.display_panels[1].data_item, document_model.data_items[1])

    def test_data_display_panel_with_controller_not_treated_as_potential_result_panel(self):
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory())
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
                workspace = document_controller.workspace_controller.new_workspace("1", {"type": "image", "controller_type": "test"})
                document_controller.workspace_controller.change_workspace(workspace)
                self.assertIsNone(document_controller.next_result_display_panel())
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_reloading_display_panel_with_exception_keeps_workspace_layout_intact(self):
        DisplayPanel._test_log_exceptions = False
        try:
            DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("error", TestWorkspaceClass.DisplayPanelControllerFactory())
            try:
                with create_memory_profile_context() as profile_context:
                    document_controller = profile_context.create_document_controller(auto_close=False)
                    document_model = document_controller.document_model
                    with contextlib.closing(document_controller):
                        workspace_2x1 = document_controller.workspace_controller.new_workspace(*get_layout("2x1"))
                        document_controller.workspace_controller.change_workspace(workspace_2x1)
                    # modify it to include a controller which raises an exception during init
                    profile_context.project_properties["workspaces"][1]["layout"]["children"][0]["controller_type"] = "error"
                    # create a new document based on the corrupt layout
                    document_controller = profile_context.create_document_controller(auto_close=False)
                    document_model = document_controller.document_model
                    with contextlib.closing(document_controller):
                        pass
                    # check to ensure that the exception didn't invalidate the entire layout
                    self.assertEqual(2, len(profile_context.project_properties["workspaces"][1].get("layout", dict()).get("children", list())))
            finally:
                DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("error")
        finally:
            DisplayPanel._test_log_exceptions = True

    def test_switching_display_panel_to_controller_from_browser_switches_to_display_item(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8)))
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory(data_item))
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
                document_model.append_data_item(data_item)
                workspace = document_controller.workspace_controller.new_workspace("1", {"type": "image"})
                document_controller.workspace_controller.change_workspace(workspace)
                display_panel = document_controller.workspace_controller.display_panels[0]
                document_controller.workspace_controller.switch_to_display_content(display_panel, "browser-display-panel")
                self.assertEqual("grid", display_panel.display_panel_type)  # check assumptions
                display_panel.change_display_panel_content({"type": "image", "controller_type": "test"})
                self.assertEqual("data_item", display_panel.display_panel_type)
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_removing_display_item_in_display_panel_to_controller_disabled_controller(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8)))
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory(data_item))
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
                document_model.append_data_item(data_item)
                workspace = document_controller.workspace_controller.new_workspace("1", {"type": "image"})
                document_controller.workspace_controller.change_workspace(workspace)
                display_panel = document_controller.workspace_controller.display_panels[0]
                display_panel.change_display_panel_content({"type": "image", "controller_type": "test"})
                self.assertIsNotNone(display_panel._display_panel_controller_for_test)
                document_model.remove_data_item(data_item)
                self.assertIsNone(display_panel._display_panel_controller_for_test)
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_data_display_panel_with_controller_only_enabled_for_primary_display_item(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8)))
        DisplayPanel.DisplayPanelManager().register_display_panel_controller_factory("test", TestWorkspaceClass.DisplayPanelControllerFactory(data_item))
        try:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_item_copy = document_model.get_display_item_copy_new(display_item)
                workspace = document_controller.workspace_controller.new_workspace("1", {"type": "image"})
                document_controller.workspace_controller.change_workspace(workspace)
                display_panel = document_controller.workspace_controller.display_panels[0]
                display_panel.set_display_panel_display_item(display_item, detect_controller=True)
                self.assertIsNotNone(display_panel._display_panel_controller_for_test)
                display_panel.set_display_panel_display_item(display_item_copy, detect_controller=True)
                self.assertIsNone(display_panel._display_panel_controller_for_test)
        finally:
            DisplayPanel.DisplayPanelManager().unregister_display_panel_controller_factory("test")

    def test_split_within_split_keeps_parent_splits(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=100, height=100))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            document_controller.selected_display_panel = display_panel
            document_controller.perform_action("workspace.split_2x2")
            root_canvas_item.layout_immediate(Geometry.IntSize(width=100, height=100))
            expected_bounds = [
                Geometry.IntRect.from_tlhw(0, 0, 50, 50),
                Geometry.IntRect.from_tlhw(0, 50, 50, 50),
                Geometry.IntRect.from_tlhw(50, 0, 50, 50),
                Geometry.IntRect.from_tlhw(50, 50, 50, 50)
            ]
            for bounds, display_panel in zip(expected_bounds, workspace_controller.display_panels):
                self.assertEqual(bounds.size, display_panel.canvas_bounds.size)
                self.assertEqual(bounds.origin, display_panel.map_to_root_container(display_panel.canvas_bounds.origin))
            document_controller.selected_display_panel = workspace_controller.display_panels[3]
            document_controller.perform_action("workspace.split_2x2")
            root_canvas_item.layout_immediate(Geometry.IntSize(width=100, height=100))
            expected_bounds = [
                Geometry.IntRect.from_tlhw(0, 0, 50, 50),
                Geometry.IntRect.from_tlhw(0, 50, 50, 50),
                Geometry.IntRect.from_tlhw(50, 0, 50, 50),
                Geometry.IntRect.from_tlhw(50, 50, 25, 25),
                Geometry.IntRect.from_tlhw(50, 75, 25, 25),
                Geometry.IntRect.from_tlhw(75, 50, 25, 25),
                Geometry.IntRect.from_tlhw(75, 75, 25, 25),
            ]
            for bounds, display_panel in zip(expected_bounds, workspace_controller.display_panels):
                self.assertEqual(bounds.size, display_panel.canvas_bounds.size)
                self.assertEqual(bounds.origin, display_panel.map_to_root_container(display_panel.canvas_bounds.origin))

    def test_drop_external_on_1x1_replace(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.workspace_controller.display_panels[0]
            display_panel.set_display_panel_display_item(display_item)
            image_path = pathlib.Path(__file__).parent.parent / "resources" / "1x1_icon.png"
            mime_data = TestUI.MimeData({"text/uri-list": pathlib.Path(image_path)})  # this is the format used by TestUI
            document_controller.workspace_controller.handle_drop(display_panel, mime_data, "none", 160, 240)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, document_model.data_items[-1])
            self.assertEqual(document_controller.workspace_controller.display_panels[0].display_panel_type, "data_item")

    def test_display_panel_next_previous_display_panel(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            workspace_controller = document_controller.workspace_controller
            display_panel = workspace_controller.display_panels[0]
            document_controller.selected_display_panel = display_panel
            document_controller.perform_action("workspace.split_2x2")
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertEqual(workspace_controller.display_panels[0], document_controller.selected_display_panel)
            display_panel._handle_key_pressed(TestUI.Key(None, "tab", None))
            self.assertEqual(workspace_controller.display_panels[1], document_controller.selected_display_panel)
            display_panel._handle_key_pressed(TestUI.Key(None, "tab", None))
            self.assertEqual(workspace_controller.display_panels[2], document_controller.selected_display_panel)
            display_panel._handle_key_pressed(TestUI.Key(None, "tab", None))
            self.assertEqual(workspace_controller.display_panels[3], document_controller.selected_display_panel)
            display_panel._handle_key_pressed(TestUI.Key(None, "tab", None))
            self.assertEqual(workspace_controller.display_panels[0], document_controller.selected_display_panel)
            display_panel._handle_key_pressed(TestUI.Key(None, "backtab", None))
            self.assertEqual(workspace_controller.display_panels[3], document_controller.selected_display_panel)
            display_panel._handle_key_pressed(TestUI.Key(None, "backtab", None))
            self.assertEqual(workspace_controller.display_panels[2], document_controller.selected_display_panel)

    def test_changing_workspace_title_updates_window_title(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            # create three workspaces
            workspace_controller = document_controller.workspace_controller
            workspace = workspace_controller._workspace
            # check assumptions
            original_name = workspace.name
            new_name = original_name + " new"
            self.assertTrue(document_controller.title.endswith(original_name))
            # change the name and check that the title updates
            command = Workspace.RenameWorkspaceCommand(workspace_controller, new_name)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertTrue(document_controller.title.endswith(new_name))
            # undo
            document_controller.handle_undo()
            document_controller.periodic()
            self.assertTrue(document_controller.title.endswith(original_name))
            # redo
            document_controller.handle_redo()
            document_controller.periodic()
            self.assertTrue(document_controller.title.endswith(new_name))

    # def test_display_panel_controller_initially_displays_existing_data(self):
    #     # cannot implement until common code for display controllers is moved into document model
    #     pass

    # def test_display_panel_controller_displays_fresh_data(self):
    #     # cannot implement until common code for display controllers is moved into document model
    #     pass

    def test_apply_layouts_return_value(self):
        """Test the apply_layouts method returns the new panels in the correct order."""
        test_cases = [(w, h) for w in range(1, 5) for h in range(1, 4)]
        with TestContext.create_memory_context() as test_context:
            for test_case in test_cases:
                with self.subTest(test_case):
                    document_controller = test_context.create_document_controller()
                    workspace_controller = document_controller.workspace_controller
                    selected_display_panel = workspace_controller.display_panels[0]
                    context = typing.cast(DocumentController.DocumentController.ActionContext, document_controller._get_action_context())
                    test_w, test_h = test_case
                    total_new_panels = test_w * test_h
                    returned_display_panels = workspace_controller.apply_layouts(selected_display_panel, context.display_panels, test_w, test_h)
                    self.assertEqual(len(returned_display_panels), total_new_panels)
                    for returned_panel, layout_panel in zip(returned_display_panels, workspace_controller.display_panels):
                        self.assertEqual(returned_panel, layout_panel)

    def __setup_split_test(self, test_context: TestContext.MemoryProfileContext, test_case: SplitCase) \
            -> tuple[DocumentController.DocumentController, list[DataItem.DataItem]]:
        """Use the test_case to set up the initial environment for a split test, returning the document controller and the ordered list of selected data items."""

        def __setup_test_data_items(data_item_count: int) -> list[DataItem.DataItem]:
            """Create the data items for a test and add them to the document model.

            Returns the data items.
            """
            data_items: list[DataItem.DataItem] = []
            for i in range(data_item_count - 1, -1, -1):  # Items are ordered by last created, so item #0 needs to be created last
                data_item = DataItem.DataItem(numpy.zeros((1, 1)))
                data_item.title = f"#{i}"  # Title is useful for debugging failures
                data_items.insert(0, data_item)

            for data_item in data_items:
                document_controller.document_model.append_data_item(data_item)

            return data_items

        def __setup_data_panel_selection(selected_data_items_indices, data_items) -> list[DataItem.DataItem]:
            """Set up the selection of items in the data panel returning the ordered selection of items"""
            selected_data_items = []
            for index, data_item in enumerate(data_items):
                if index in selected_data_items_indices:
                    selected_data_items.append(data_item)
            document_controller.select_data_items_in_data_panel(selected_data_items)
            return selected_data_items

        def __setup_initial_workspace(initial_workspace_layout, selected_workspace_panels_indices) \
                -> None:
            """Set up the workspace before preforming the split tests.

            After the workspace is created the display panels are iterated through and set as selected based on if it appears in the selected_workspace_panels_indices.
            The document controller's selected display panel is set along with any secondary display panels in the selection.
            """
            _, layout_d = get_layout(initial_workspace_layout)

            workspace = document_controller.workspace_controller.new_workspace("layout", layout=layout_d)

            workspace_controller = document_controller.workspace_controller
            workspace_controller.change_workspace(workspace)

            selected_display_panels = []
            for index, display_panel in enumerate(workspace_controller.display_panels):
                is_selected = index in selected_workspace_panels_indices
                display_panel.set_selected(is_selected)
                if is_selected:
                    selected_display_panels.append(display_panel)
                    if len(selected_display_panels) == 1:  # Only set the selected_display_panel for the first one, any others will be secondary.
                        document_controller.selected_display_panel = display_panel
                        document_controller.selected_display_panel.request_focus()  # This ensures the focus_widget is valid

            document_controller.clear_secondary_display_panels()
            for display_panel in selected_display_panels:
                if display_panel != document_controller.selected_display_panel:
                    document_controller.add_secondary_display_panel(display_panel)

        def __setup_display_panels(workspace_data_display_panels_indices,
                                   selected_workspace_panels_indices, selected_data_items, data_items) \
                -> list[DataItem.DataItem]:
            """Set the data items of display panels that are meant to have one, adding any that are selected to the ordered selected data item list which is then returned.

            The selected display panels with items are expected to come in order before any data panel items.
            """
            selected_display_panels_data_items = []
            for display_panel_index, data_item_index in workspace_data_display_panels_indices:
                data_item = data_items[data_item_index]
                document_controller.workspace_controller.display_panels[display_panel_index].set_displayed_data_item(data_item)
                if display_panel_index in selected_workspace_panels_indices:
                    selected_display_panels_data_items.append(data_item)

            selected_display_panels_data_items.extend(selected_data_items)  # The selections data panel items come after any selected display panel data items
            return selected_display_panels_data_items

        document_controller = test_context.create_document_controller()
        all_data_items = __setup_test_data_items(test_case.total_data_items)
        ordered_selected_data_items = __setup_data_panel_selection(test_case.selected_data_items_indices, all_data_items)
        __setup_initial_workspace(test_case.initial_layout_id, test_case.selected_workspace_panels_indices)
        ordered_selected_data_items = __setup_display_panels(test_case.workspace_display_data_items_indices, test_case.selected_workspace_panels_indices, ordered_selected_data_items, all_data_items)
        return document_controller, ordered_selected_data_items

    def copy_display_panel_uuids(self, display_panels: typing.Sequence[DisplayPanel.DisplayPanel]) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
        return [(display_panel.uuid, display_panel.data_item.uuid if display_panel.data_item is not None else None) for display_panel in display_panels]

    def run_disabled_split_test(self, test_case: SplitCase, perform_func: typing.Callable[[DocumentController.DocumentController], None]):
        """Test there is no change for invalid test cases.

        Setup the selection using the test_case and then run perform_func with the document controller to call the action.
        """
        with TestContext.create_memory_context() as test_context:
            document_controller, _ = self.__setup_split_test(test_context, test_case)
            workspace_controller = document_controller.workspace_controller
            starting_display_panels = workspace_controller.display_panels
            perform_func(document_controller)
            self.assertEqual(starting_display_panels, workspace_controller.display_panels)

    def _verify_split_results(self, document_controller: DocumentController.DocumentController, selected_data_items: list[DataItem.DataItem], test_case: SplitCase, initial_display_panels: list[tuple[uuid.UUID, uuid.UUID | None]]) -> None:
        """Verify the number, shape, and order of the created panels, as well as the undo and redo."""

        def _verify_created_panels_order(selected_panel_index: int) -> None:
            """Assert that the new panels are in the expected order

            The expected order is passed in the selected_data_items.
            The new display panels are sliced from the document controller's display panels from the selected_panel_index.
            """
            new_panels = document_controller.workspace_controller.display_panels[selected_panel_index:selected_panel_index + len(selected_data_items)]
            for new_display_panel, selected_item in zip(new_panels, selected_data_items):
                self.assertEqual(new_display_panel.data_item, selected_item, msg=f"Order mismatch for newly created items {new_display_panel.data_item.title}!={selected_item.title}")

        def _verify_layout_shape(expected_h: int, expected_w: int, parent: CanvasItem.CanvasItemComposition | None = None) -> None:
            """Assert that the shape of the new panels is the expected (h, w).

            The first selected display panel's parent is used to get the number of panels in that row, then checked against the expected horizonal.
            If there is a vertical split, the parent's parent is used to get the number of panels in the column which is checked against the expected vertical.
            """
            if parent is None:
                parent: CanvasItem.CanvasItemComposition | None = None
                for display_panel in document_controller.workspace_controller.display_panels:
                    if display_panel.data_item in selected_data_items:
                        parent = display_panel.container
                        break
            self.assertIsNotNone(parent, msg="No selected items were in the display panels, unable to determine the new panels shape.")
            if expected_h == expected_w == 1:
                self.assertEqual(1, parent.canvas_items_count, msg="Parent of the selected item contained more than one child.")
            else:
                if expected_w != 1:
                    self.assertIsNotNone(parent.container, msg="No parent contain, unable to determine vertical split where one was expected.")
                    self.assertEqual(expected_w, parent.container.canvas_items_count, msg="Incorrect Vertical split.")

                self.assertEqual(expected_h, parent.canvas_items_count, msg="Incorrect Horizontal split.")

        def _verify_undo_redo_works() -> None:
            workspace_controller = document_controller.workspace_controller
            document_controller.handle_undo()
            self.assertEqual(len(initial_display_panels), len(workspace_controller.display_panels))

            for (initial_panel_uuid, initial_display_item_uuid), current_panel in zip(initial_display_panels, workspace_controller.display_panels):
                self.assertEqual(initial_panel_uuid, current_panel.uuid)
                if initial_display_item_uuid is not None or current_panel.data_item is not None:
                    self.assertEqual(initial_display_item_uuid, current_panel.data_item.uuid)

            initial_h, initial_w = test_case.initial_shape
            _verify_layout_shape(initial_h, initial_w, workspace_controller.display_panels[0].container)

            document_controller.handle_redo()  # now redo
            _verify_layout_shape(test_case.expected_h, test_case.expected_w)
            _verify_created_panels_order(test_case.selected_panel_index)

        self.assertEqual(test_case.total_expected_panels, len(document_controller.workspace_controller.display_panels))
        _verify_layout_shape(test_case.expected_h, test_case.expected_w)
        _verify_created_panels_order(test_case.selected_panel_index)
        _verify_undo_redo_works()

    def run_split_test(self, test_case: SplitCase, perform_func: typing.Callable[[DocumentController.DocumentController], None]) -> None:
        """Test a split in test_case against the expected result.

        Set up the selection using the test_case and then run perform_func with the document controller to call the action.
        """
        with TestContext.create_memory_context() as test_context:
            document_controller, selected_data_items = self.__setup_split_test(test_context, test_case)
            initial_display_panels = self.copy_display_panel_uuids(document_controller.workspace_controller.display_panels)

            perform_func(document_controller)
            self._verify_split_results(document_controller, selected_data_items, test_case, initial_display_panels)

    def perform_split_selection(self, document_controller: DocumentController.DocumentController):
        """The perform_func to be passed into the run_split_test function for the workspace.split_from_selection tests"""
        action_context = document_controller._get_action_context()
        document_controller.perform_action_in_context("workspace.split_from_selection", action_context)

    def test_split_disabled_when_no_data_panel_items_selected(self):
        test_case = SplitCase(selected_data_items_indices=[], selected_workspace_panels_indices=[0], total_data_items=1)
        self.run_disabled_split_test(test_case, self.perform_split_selection)

    def test_split_disabled_when_no_display_panel_selected(self):
        test_case = SplitCase(selected_data_items_indices=[0], selected_workspace_panels_indices=[], total_data_items=1)
        self.run_disabled_split_test(test_case, self.perform_split_selection)

    def test_split_disabled_when_too_many_items_selected(self):
        test_case = SplitCase(selected_data_items_indices=[x for x in range(0, 102)], selected_workspace_panels_indices=[0], total_data_items=102)
        self.run_disabled_split_test(test_case, self.perform_split_selection)

    def test_split_disabled_when_too_many_display_panels_selected(self):
        test_case = SplitCase(selected_data_items_indices=[0], selected_workspace_panels_indices=[0, 1], total_data_items=1, initial_layout_id="2x1")
        self.run_disabled_split_test(test_case, self.perform_split_selection)

    def test_split_inserts_single_item(self):
        test_case = SplitCase(selected_workspace_panels_indices=0, expected_split_shape=(1, 1), total_expected_panels=1, selected_data_items_indices=[0], total_data_items=1)
        self.run_split_test(test_case, self.perform_split_selection)

    def test_split_inserts_two_items(self):
        test_case = SplitCase(selected_workspace_panels_indices=0, expected_split_shape=(2, 1), total_expected_panels=2, selected_data_items_indices=[0, 1], total_data_items=2)
        self.run_split_test(test_case, self.perform_split_selection)

    def test_split_inserts_five_items(self):
        test_case = SplitCase(selected_workspace_panels_indices=0, expected_split_shape=(3, 2), total_expected_panels=6, selected_data_items_indices=[0, 1, 2, 3, 4], total_data_items=5)
        self.run_split_test(test_case, self.perform_split_selection)

    def test_split_with_panel_item(self):  # 1 panel with an existing data item, 4 selected data items, will be split into 3x2 since the existing makes the total 5
        test_case = SplitCase(selected_workspace_panels_indices=0, expected_split_shape=(3, 2), total_expected_panels=6, selected_data_items_indices=[1, 2, 3, 4], total_data_items=5, workspace_data_items_indices=[(0, 0)])
        self.run_split_test(test_case, self.perform_split_selection)

    def test_split_with_right_selected(self):  # 2 panels right selected, 5 data items split will be 3x2 with one empty
        test_case = SplitCase(selected_workspace_panels_indices=1, expected_split_shape=(3, 2), total_expected_panels=7, selected_data_items_indices=[0, 1, 2, 3, 4], total_data_items=5, initial_layout_id="2x1")
        self.run_split_test(test_case, self.perform_split_selection)

    def test_split_with_bottom_selected(self):   # 2 panels bottom selected, 5 data items split will be 3x2 with one empty
        test_case = SplitCase(selected_workspace_panels_indices=1, expected_split_shape=(3, 2), total_expected_panels=7, selected_data_items_indices=[0, 1, 2, 3, 4], total_data_items=5, initial_layout_id="2x1")
        self.run_split_test(test_case, self.perform_split_selection)

    def test_split_with_existing_item(self):  # 2 panels, second with an existing data item and selected, 4 selected data items, will be split into 3x2 since the existing makes the total 5
        test_case = SplitCase(selected_workspace_panels_indices=1, expected_split_shape=(3, 2), total_expected_panels=7, selected_data_items_indices=[1, 2, 3, 4], total_data_items=5, workspace_data_items_indices=[(1, 0)], initial_layout_id="2x1")
        self.run_split_test(test_case, self.perform_split_selection)

    def test_split_with_existing_items(self):  # 2 panels with an existing data items, only second selected, 4 selected data items, will be split into 3x2 since the existing makes the total 5
        test_case = SplitCase(selected_workspace_panels_indices=1, expected_split_shape=(3, 2), total_expected_panels=7, selected_data_items_indices=[1, 2, 3, 4], total_data_items=6, workspace_data_items_indices=[(0, 5), (1, 0)], initial_layout_id="2x1")
        self.run_split_test(test_case, self.perform_split_selection)

    def perform_new_workspace_from_selection(self, document_controller: DocumentController.DocumentController) -> None:
        """The perform_func to be passed into the run_split_test function for the workspace.new_workspace_from_selection tests.

        Since invoke would bring up a text input dialog for the name, the context needs to be setup with the name already defined
        then execute the action if it is enabled.
        """
        action_context = document_controller._get_action_context()
        new_workspace_action = Window.actions["workspace.new_workspace_from_selection"]
        new_workspace_action.set_string_property(action_context, "name", "New Workspace")
        if new_workspace_action.is_enabled(action_context):
            _ = new_workspace_action.execute(action_context)

    def test_new_workspace_disabled_no_item(self):  # No selected data items, no change
        test_case = SplitCase(selected_workspace_panels_indices=0, selected_data_items_indices=[], total_data_items=0, initial_layout_id="2x1")
        self.run_disabled_split_test(test_case, self.perform_new_workspace_from_selection)

    def test_new_workspace_disabled_too_many_items(self):  # Too many selected items, no change
        test_case = SplitCase(selected_workspace_panels_indices=0, selected_data_items_indices=[x for x in range(0, 102)], total_data_items=101, initial_layout_id="2x1")
        self.run_disabled_split_test(test_case, self.perform_new_workspace_from_selection)

    def test_new_workspace_disabled_too_many_total(self):  # Total selected data items (6 display panel items, 95 data panel items) is too large, no change
        test_case = SplitCase(selected_workspace_panels_indices=[i for i in range(0, 6)], selected_data_items_indices=[x for x in range(6, 102)], total_data_items=101, initial_layout_id="3x2", workspace_data_items_indices=[(i, i) for i in range(0, 6)])
        self.run_disabled_split_test(test_case, self.perform_new_workspace_from_selection)

    def test_new_workspace_single_item(self):  # 1 data item selected becomes a workspace with that item
        test_case = SplitCase(selected_workspace_panels_indices=0, selected_data_items_indices=[0], total_expected_panels=1, total_data_items=1, initial_layout_id="2x1", expected_split_shape=(1, 1))
        self.run_split_test(test_case, self.perform_new_workspace_from_selection)

    def test_new_workspace_five_items(self):  # 5 data items selected becomes a workspace split 3x2
        test_case = SplitCase(selected_workspace_panels_indices=0, selected_data_items_indices=[0, 1, 2, 3, 4], total_expected_panels=6, total_data_items=5, initial_layout_id="2x1", expected_split_shape=(3, 2))
        self.run_split_test(test_case, self.perform_new_workspace_from_selection)

    def test_new_workspace_panel_item(self):  # 1 workspace panel item selected becomes a workspace with that item
        test_case = SplitCase(selected_workspace_panels_indices=[0], selected_data_items_indices=[], total_expected_panels=1, total_data_items=1, initial_layout_id="2x1", expected_split_shape=(1, 1), workspace_data_items_indices=[(0, 0)])
        self.run_split_test(test_case, self.perform_new_workspace_from_selection)

    def test_new_workspace_five_panel_items(self):  # 5 data panel items selected becomes a workspace split 3x2
        test_case = SplitCase(selected_workspace_panels_indices=[0, 1, 2, 3, 4], selected_data_items_indices=[], total_expected_panels=6, total_data_items=5, initial_layout_id="6x1", expected_split_shape=(3, 2), workspace_data_items_indices=[(i, i) for i in range(0, 5)])
        self.run_split_test(test_case, self.perform_new_workspace_from_selection)

    def test_new_workspace_two_in_mixed_selection(self):  # 1 data panel item and 1 display panel item selected becomes a workspace split 2x1
        test_case = SplitCase(selected_workspace_panels_indices=[0], selected_data_items_indices=[0], total_expected_panels=2, total_data_items=2, initial_layout_id="6x1", expected_split_shape=(2, 1), workspace_data_items_indices=[(0, 1)])
        self.run_split_test(test_case, self.perform_new_workspace_from_selection)

    def test_new_workspace_five_in_mixed_selection(self):  # 2 data panel items and 3 display panel items selected becomes a workspace split 3x2
        test_case = SplitCase(selected_workspace_panels_indices=[i for i in range(0, 3)], selected_data_items_indices=[0, 1], total_expected_panels=6, total_data_items=5, initial_layout_id="3x1", expected_split_shape=(3, 2), workspace_data_items_indices=[(i - 2, i) for i in range(2, 5)])
        self.run_split_test(test_case, self.perform_new_workspace_from_selection)

    def test_new_workspace_empty_panels_in_selection(self):  # 4 data panel items and 4 display panel items selected becomes a workspace split 4x2, the empty display panels that are selected are not used
        test_case = SplitCase(selected_workspace_panels_indices=[0, 1, 2, 3, 4, 5], selected_data_items_indices=[4, 5, 6, 7], total_expected_panels=8, total_data_items=8, initial_layout_id="6x1", expected_split_shape=(4, 2), workspace_data_items_indices=[(i, i) for i in range(0, 4)])
        self.run_split_test(test_case, self.perform_new_workspace_from_selection)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
