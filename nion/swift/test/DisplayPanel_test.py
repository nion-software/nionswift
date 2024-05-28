# standard libraries
import contextlib
import logging
import math
import typing
import unittest
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import DisplayPanel
from nion.swift import Facade
from nion.swift import ImageCanvasItem
from nion.swift import LinePlotCanvasItem
from nion.swift import MimeTypes
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.test import TestContext
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import TestUI
from nion.ui import UserInterface
from nion.utils import Geometry
from nion.utils import ListModel

Facade.initialize()


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestGraphicSelectionClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_selection_set(self):
        selection = DisplayItem.GraphicSelection()
        selection.set(0)
        selection.set(1)
        self.assertEqual(len(selection.indexes), 1)


def create_1d_data(length=1024, data_min=0.0, data_max=1.0):
    data = numpy.zeros((length, ), dtype=float)
    irow = numpy.ogrid[0:length]
    data[:] = data_min + (data_max - data_min) * (irow / float(length))
    return data


class TestDisplayPanel:
    def __init__(self) -> None:
        self.drop_region = None

    def handle_drag_enter(self, mime_data: UserInterface.MimeData) -> str:
        return "copy"

    def handle_drag_move(self, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
        return "copy"

    def handle_drop(self, mime_data: UserInterface.MimeData, region, x: int, y: int) -> str:
        self.drop_region = region
        return "copy"


class TestDisplayPanelClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.test_context = TestContext.create_memory_context()
        self.test_context.__enter__()
        self.document_controller = self.test_context.create_document_controller_with_application()
        self.document_model = self.document_controller.document_model
        self.display_panel = self.document_controller.selected_display_panel
        self.data_item = DataItem.DataItem(numpy.zeros((10, 10)))
        self.document_model.append_data_item(self.data_item)
        self.display_item = self.document_model.get_display_item_for_data_item(self.data_item)
        self.display_panel.set_display_panel_display_item(self.display_item)
        header_height = self.display_panel.header_canvas_item.header_height
        self.display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))

    def tearDown(self):
        self.test_context.__exit__(None, None, None)
        self.test_context.close()
        TestContext.end_leaks(self)

    def setup_line_plot(self, canvas_shape=None, data_min=0.0, data_max=1.0):
        canvas_shape = canvas_shape if canvas_shape else (480, 640)  # yes I know these are backwards
        data_item_1d = DataItem.DataItem(create_1d_data(data_min=data_min, data_max=data_max))
        self.document_model.append_data_item(data_item_1d)
        display_item_1d = self.document_model.get_display_item_for_data_item(data_item_1d)
        self.display_panel.set_display_panel_display_item(display_item_1d)
        self.display_panel.display_canvas_item.layout_immediate(canvas_shape)
        self.display_panel_drawing_context = DrawingContext.DrawingContext()
        self.display_item = display_item_1d
        self.display_panel.display_canvas_item.refresh_layout_immediate()
        return self.display_panel.display_canvas_item

    def setup_3d_data(self, canvas_shape=None):
        canvas_shape = canvas_shape if canvas_shape else (640, 480)  # yes I know these are backwards
        data_item_3d = DataItem.DataItem(numpy.ones((5, 5, 5)))
        self.document_model.append_data_item(data_item_3d)
        display_item_3d = self.document_model.get_display_item_for_data_item(data_item_3d)
        self.display_panel.set_display_panel_display_item(display_item_3d)
        self.display_panel.display_canvas_item.layout_immediate(canvas_shape)
        self.display_panel_drawing_context = DrawingContext.DrawingContext()
        self.display_item = display_item_3d
        # trigger layout
        return self.display_panel.display_canvas_item

    def test_image_panel_gets_destructed(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            display_panel = DisplayPanel.DisplayPanel(document_controller, dict())
            # add some extra refs for fun
            container = CanvasItem.SplitterCanvasItem()
            container.add_canvas_item(display_panel)
            canvas_widget = self.document_controller.ui.create_canvas_widget()
            with contextlib.closing(canvas_widget):
                canvas_widget.canvas_item.add_canvas_item(container)
                # now take the weakref
                display_panel_weak_ref = weakref.ref(display_panel)
                display_panel = None
            self.assertIsNone(display_panel_weak_ref())

    # user deletes data item that is displayed. make sure we remove the display.
    def test_deleting_data_item_removes_it_from_image_panel(self):
        self.assertEqual(self.data_item, self.document_model.data_items[0])
        self.assertEqual(self.display_item.data_item, self.data_item)
        self.document_controller.processing_invert()
        self.document_controller.periodic()
        self.display_panel.set_display_panel_display_item(self.display_item)
        self.assertEqual(self.display_panel.data_item, self.data_item)
        self.document_model.remove_data_item(self.data_item)
        self.assertIsNone(self.display_panel.data_item)

    # user deletes data source of data item that is displayed. make sure to remove display if source is deleted.
    def test_deleting_data_item_with_processed_data_item_removes_processed_data_item_from_image_panel(self):
        self.assertEqual(self.display_panel.data_item, self.document_model.data_items[0])
        self.assertEqual(self.display_panel.data_item, self.data_item)
        inverted_data_item = self.document_controller.processing_invert().data_item
        inverted_display_item = self.document_model.get_display_item_for_data_item(inverted_data_item)
        self.document_controller.periodic()
        self.display_panel.set_display_panel_display_item(inverted_display_item)
        self.assertEqual(self.display_panel.data_item, inverted_data_item)
        self.document_model.remove_data_item(self.data_item)
        self.assertIsNone(self.display_panel.data_item)

    def test_select_line(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_graphic()
        # click outside so nothing is selected
        self.display_panel.display_canvas_item.simulate_click((0, 0))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 0)
        # select the line
        self.display_panel.display_canvas_item.simulate_click((200, 200))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_item.graphic_selection.indexes)
        # now shift the view and try again
        self.display_panel.display_canvas_item.simulate_click((0, 0))
        self.document_controller.periodic()
        self.display_panel.display_canvas_item.move_left()  # 10 pixels left
        self.display_panel.display_canvas_item.move_left()  # 10 pixels left
        self.display_panel.display_canvas_item.refresh_layout_immediate()
        self.display_panel.display_canvas_item.simulate_click((200, 200))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 0)
        self.display_panel.display_canvas_item.simulate_click((220, 200))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_item.graphic_selection.indexes)

    def test_select_multiple(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_graphic()
        self.document_controller.add_ellipse_graphic()
        # click outside so nothing is selected
        self.display_panel.display_canvas_item.simulate_click((0, 0))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 0)
        # select the ellipse
        self.display_panel.display_canvas_item.simulate_click((725, 500))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertTrue(1 in self.display_item.graphic_selection.indexes)
        # select the line
        self.display_panel.display_canvas_item.simulate_click((200, 200))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_item.graphic_selection.indexes)
        # add the ellipse to the selection. click inside the right side.
        self.display_panel.display_canvas_item.simulate_click((725, 500), CanvasItem.KeyboardModifiers(control=True))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 2)
        self.assertTrue(0 in self.display_item.graphic_selection.indexes)
        # remove the ellipse from the selection. click inside the right side.
        self.display_panel.display_canvas_item.simulate_click((725, 500), CanvasItem.KeyboardModifiers(control=True))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_item.graphic_selection.indexes)

    def assertClosePoint(self, p1, p2, e=0.00001):
        self.assertTrue(Geometry.distance(p1, p2) < e)

    def assertCloseRectangle(self, r1, r2, e=0.00001):
        self.assertTrue(Geometry.distance(r1[0], r2[0]) < e and Geometry.distance(r1[1], r2[1]) < e)

    def test_drag_multiple(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_graphic()
        self.document_controller.add_ellipse_graphic()
        # make sure items are in the right place
        self.assertClosePoint(self.display_item.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.display_item.graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.display_item.graphics[1].bounds, ((0.25, 0.25), (0.5, 0.5)))
        # select both
        self.display_item.graphic_selection.set(0)
        self.display_item.graphic_selection.add(1)
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 2)
        # drag by (0.1, 0.2)
        self.display_panel.display_canvas_item.simulate_drag((500,500), (600,700))
        self.document_controller.periodic()
        self.assertCloseRectangle(self.display_item.graphics[1].bounds, ((0.35, 0.45), (0.5, 0.5)))
        self.assertClosePoint(self.display_item.graphics[0].start, (0.3, 0.4))
        self.assertClosePoint(self.display_item.graphics[0].end, (0.9, 1.0))
        # drag on endpoint (0.3, 0.4) make sure it drags all
        self.display_panel.display_canvas_item.simulate_drag((300,400), (200,200))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.display_item.graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.display_item.graphics[1].bounds, ((0.25, 0.25), (0.5, 0.5)))
        # now select just the line, drag middle of circle. should only drag circle.
        self.display_item.graphic_selection.set(0)
        self.display_panel.display_canvas_item.simulate_drag((700,500), (800,500))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.display_item.graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.display_item.graphics[1].bounds, ((0.35, 0.25), (0.5, 0.5)))

    def test_drag_line_part(self):
        # add line (0.2, 0.2), (0.8, 0.8)
        self.document_controller.add_line_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_item.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.display_item.graphics[0].end, (0.8, 0.8))
        # select it
        self.display_item.graphic_selection.set(0)
        self.display_panel.display_canvas_item.simulate_drag((200,200), (300,400))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (0.3, 0.4))
        self.assertClosePoint(self.display_item.graphics[0].end, (0.8, 0.8))
        # shift drag a part, should not deselect and should align horizontally
        self.display_panel.display_canvas_item.simulate_drag((300,400), (350,700), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertClosePoint(self.display_item.graphics[0].start, (0.35, 0.8))
        # shift drag start to top left quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((350,800), (370,340), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (0.34, 0.34))
        self.display_panel.display_canvas_item.simulate_drag((340,340), (240,270), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (0.24, 0.24))
        # shift drag start to bottom left quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((240,240), (370,1140), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (0.37, 1.23))
        self.display_panel.display_canvas_item.simulate_drag((370,1230), (370,1350), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (0.25, 1.35))
        # shift drag start to bottom right quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((250,1350), (1230,1175), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (1.23, 1.23))
        self.display_panel.display_canvas_item.simulate_drag((1230,1230), (1150,1210), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (1.21, 1.21))
        # shift drag start to top right quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((1210,1210), (1230,310), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (1.29, 0.31))
        self.display_panel.display_canvas_item.simulate_drag((1290,310), (1110,420), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].start, (1.18, 0.42))
        # now reverse start/end and run the same test
        self.display_panel.display_canvas_item.simulate_drag((800,800), (200,200))
        self.document_controller.periodic()
        self.display_panel.display_canvas_item.simulate_drag((1180,420), (800,800))
        self.document_controller.periodic()
        # shift drag start to top left quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((200,200), (370,340), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].end, (0.34, 0.34))
        self.display_panel.display_canvas_item.simulate_drag((340,340), (240,270), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].end, (0.24, 0.24))
        # shift drag start to bottom left quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((240,240), (370,1140), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].end, (0.37, 1.23))
        self.display_panel.display_canvas_item.simulate_drag((370,1230), (370,1350), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].end, (0.25, 1.35))
        # shift drag start to bottom right quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((250,1350), (1230,1175), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].end, (1.23, 1.23))
        self.display_panel.display_canvas_item.simulate_drag((1230,1230), (1150,1210), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].end, (1.21, 1.21))
        # shift drag start to top right quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((1210,1210), (1230,310), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].end, (1.29, 0.31))
        self.display_panel.display_canvas_item.simulate_drag((1290,310), (1110,420), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].end, (1.18, 0.42))

    def test_nudge_line(self):
        # add line (0.2, 0.2), (0.8, 0.8)
        self.document_controller.add_line_graphic()
        # select it
        self.display_item.graphic_selection.set(0)
        # move it left
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("left"))
        self.assertClosePoint(self.display_item.graphics[0].start, (0.200, 0.199))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("left", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].start, (0.200, 0.189))
        # move it up
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("up"))
        self.assertClosePoint(self.display_item.graphics[0].start, (0.199, 0.189))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("up", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].start, (0.189, 0.189))
        # move it right
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("right"))
        self.assertClosePoint(self.display_item.graphics[0].start, (0.189, 0.190))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("right", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].start, (0.189, 0.200))
        # move it down
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("down"))
        self.assertClosePoint(self.display_item.graphics[0].start, (0.190, 0.200))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("down", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].start, (0.200, 0.200))

    def test_nudge_rect(self):
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_rectangle_graphic()
        # select it
        self.display_item.graphic_selection.set(0)
        # move it left
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("left"))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.250, 0.249))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("left", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.250, 0.239))
        # move it up
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("up"))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.249, 0.239))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("up", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.239, 0.239))
        # move it right
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("right"))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.239, 0.240))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("right", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.239, 0.250))
        # move it down
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("down"))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.240, 0.250))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("down", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.250, 0.250))

    def test_nudge_ellipse(self):
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_ellipse_graphic()
        # select it
        self.display_item.graphic_selection.set(0)
        # move it left
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("left"))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.250, 0.249))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("left", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.250, 0.239))
        # move it up
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("up"))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.249, 0.239))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("up", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.239, 0.239))
        # move it right
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("right"))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.239, 0.240))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("right", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.239, 0.250))
        # move it down
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("down"))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.240, 0.250))
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("down", self.document_controller.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.250, 0.250))

    def test_drag_point_moves_the_point_graphic(self):
        # add point (0.5, 0.5)
        self.document_controller.add_point_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_item.graphics[0].position, (0.5, 0.5))
        # select it
        self.display_item.graphic_selection.set(0)
        self.display_panel.display_canvas_item.simulate_drag((500,500), (300,400))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].position, (0.3, 0.4))

    def test_click_on_point_selects_it(self):
        # add point (0.5, 0.5)
        self.document_controller.add_point_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_item.graphics[0].position, (0.5, 0.5))
        # select it
        self.display_panel.display_canvas_item.simulate_click((100,100))
        self.document_controller.periodic()
        self.assertFalse(self.display_item.graphic_selection.indexes)
        self.display_panel.display_canvas_item.simulate_click((500,500))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_item.graphic_selection.indexes)

    # this helps test out cursor positioning
    def test_map_widget_to_image(self):
        # assumes the test widget is 640x480
        self.display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
        self.assertIsNotNone(self.display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(240, 320)))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(240, 320)), (5, 5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(0, 80)), (0.0, 0.0))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(480, 560)), (10, 10))

    # this helps test out cursor positioning
    def test_map_widget_to_offset_image(self):
        # assumes the test widget is 640x480
        self.display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
        self.display_panel.display_canvas_item.move_left()  # 10 pixels left
        self.display_panel.display_canvas_item.move_left()  # 10 pixels left
        self.assertIsNotNone(self.display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(240, 320)))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(240, 300)), (5, 5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(0, 60)), (0.0, 0.0))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image(Geometry.IntPoint(480, 540)), (10, 10))

    def test_moving_image_updates_display_properties(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
            # establish display properties
            display_panel.display_canvas_item.move_left()
            display_panel.display_canvas_item.move_right()
            self.assertEqual((0.5, 0.5), tuple(display_item.display_properties["image_position"]))
            # move and ensure value was updated
            display_panel.display_canvas_item.move_left()  # 10 pixels left
            self.assertNotEqual((0.5, 0.5), tuple(display_item.display_properties["image_position"]))

    def test_resize_rectangle(self):
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_rectangle_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.display_item.graphics[0].bounds[1], (0.5, 0.5))
        # select it
        self.display_item.graphic_selection.set(0)
        # drag top left corner
        self.display_panel.display_canvas_item.simulate_drag((250,250), (300,250))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.30, 0.25))
        self.assertClosePoint(self.display_item.graphics[0].bounds[1], (0.45, 0.5))
        # drag with shift key
        self.display_panel.display_canvas_item.simulate_drag((300,250), (350,250), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.display_item.graphics[0].bounds[1], (0.5, 0.5))

    def test_resize_nonsquare_rectangle(self):
        self.data_item = DataItem.DataItem(numpy.zeros((20, 10)))
        self.document_model.append_data_item(self.data_item)
        self.display_item = self.document_model.get_display_item_for_data_item(self.data_item)
        self.display_panel.set_display_panel_display_item(self.display_item)
        self.display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=2000, width=1000))
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_rectangle_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.display_item.graphics[0].bounds[1], (0.5, 0.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.origin), (5, 2.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.size.as_point()), (10, 5))
        # select it
        self.display_item.graphic_selection.set(0)
        # drag top left corner
        self.display_panel.display_canvas_item.simulate_drag((500,250), (800,250))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.origin), (8, 2.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.size.as_point()), (7, 5))
        # drag with shift key
        self.display_panel.display_canvas_item.simulate_drag((800,250), (900,250), CanvasItem.KeyboardModifiers(shift=True))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.origin), (9, 1.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.size.as_point()), (6, 6))

    def test_resize_nonsquare_ellipse(self):
        self.data_item = DataItem.DataItem(numpy.zeros((20, 10)))
        self.document_model.append_data_item(self.data_item)
        self.display_item = self.document_model.get_display_item_for_data_item(self.data_item)
        self.display_panel.set_display_panel_display_item(self.display_item)
        self.display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=2000, width=1000))
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_ellipse_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_item.graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.display_item.graphics[0].bounds[1], (0.5, 0.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.origin), (5, 2.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.size.as_point()), (10, 5))
        # select it
        self.display_item.graphic_selection.set(0)
        # drag top left corner
        self.display_panel.display_canvas_item.simulate_drag((500,250), (800,250), CanvasItem.KeyboardModifiers(alt=False))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.origin), (8, 2.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.size.as_point()), (4, 5))
        # drag with shift key
        self.display_panel.display_canvas_item.simulate_drag((800,250), (900,250), CanvasItem.KeyboardModifiers(shift=True, alt=False))
        self.document_controller.periodic()
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.origin), (9, 4))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_item.graphics[0].bounds.size.as_point()), (2, 2))

    def test_insert_remove_graphics_and_selection(self):
        self.assertFalse(self.display_item.graphic_selection.indexes)
        self.document_controller.add_rectangle_graphic()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_item.graphic_selection.indexes)
        graphic = Graphics.RectangleGraphic()
        graphic.bounds = ((0.5,0.5), (0.25,0.25))
        self.display_item.insert_graphic(0, graphic)
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertTrue(1 in self.display_item.graphic_selection.indexes)
        self.display_item.remove_graphic(self.display_item.graphics[0]).close()
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_item.graphic_selection.indexes)

    def test_delete_key_when_graphic_selected_removes_the_graphic(self):
        self.document_controller.add_rectangle_graphic()
        modifiers = CanvasItem.KeyboardModifiers()
        # focus click
        self.display_panel.root_container.canvas_widget.simulate_mouse_click(500, 500, modifiers)  # click on graphic
        # check assumptions
        self.assertEqual(len(self.display_item.graphics), 1)
        self.assertEqual(len(self.display_item.graphic_selection.indexes), 1)
        # do focusing click, then delete
        self.display_panel.root_container.canvas_widget.on_key_pressed(TestUI.Key(None, "delete", modifiers))
        # check results
        self.assertEqual(len(self.display_item.graphics), 0)

    def test_delete_key_when_nothing_selected_does_nothing(self):
        modifiers = CanvasItem.KeyboardModifiers()
        # check assumptions
        self.assertIsNotNone(self.display_panel.data_item)
        # do focusing click, then delete
        self.display_panel.root_container.canvas_widget.simulate_mouse_click(100, 100, modifiers)
        self.display_panel.root_container.canvas_widget.on_key_pressed(TestUI.Key(None, "delete", modifiers))
        # check results
        self.assertIsNotNone(self.display_panel.data_item)

    def test_default_display_for_1xN_data_is_line_plot(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((1, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            self.assertIsInstance(display_panel.display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)

    def test_line_plot_initially_displays_entire_data_in_horizontal_direction(self):
        line_plot_canvas_item = self.setup_line_plot()
        self.assertEqual(line_plot_canvas_item.line_graph_layers_canvas_item._axes.drawn_left_channel, 0)
        self.assertEqual(line_plot_canvas_item.line_graph_layers_canvas_item._axes.drawn_right_channel, 1024)

    def test_line_plot_initially_displays_entire_data_in_vertical_direction(self):
        line_plot_canvas_item = self.setup_line_plot()
        self.assertEqual(line_plot_canvas_item.line_graph_layers_canvas_item._axes.uncalibrated_data_min, 0.0)
        self.assertEqual(line_plot_canvas_item.line_graph_layers_canvas_item._axes.uncalibrated_data_max, 1.0)

    def test_mouse_tracking_moves_horizontal_scale(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_horizontal(Geometry.IntPoint(x=320, y=465), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=360, y=465), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        offset = -1024.0 * 40.0 / plot_width
        self.assertEqual(self.display_item.get_display_property("left_channel"), int(offset))
        self.assertEqual(self.display_item.get_display_property("right_channel"), int(1024 + offset))

    def test_mouse_tracking_moves_vertical_scale(self):
        line_plot_canvas_item = self.setup_line_plot()
        # notice: dragging increasing y drags down.
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        offset = -1.0 * 30.0 / plot_height
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), 0.0 + offset)
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), 1.0 + offset)

    def test_mouse_tracking_moves_vertical_scale_with_calibrated_data_with_offset(self):
        # notice: dragging increasing y drags down.
        line_plot_canvas_item = self.setup_line_plot()
        data_item = self.display_item.data_item
        intensity_calibration = data_item.intensity_calibration
        intensity_calibration.offset = 0.2
        data_item.set_intensity_calibration(intensity_calibration)
        calibrated_data_min = line_plot_canvas_item.line_graph_layers_canvas_item._axes.calibrated_data_min
        calibrated_data_max = line_plot_canvas_item.line_graph_layers_canvas_item._axes.calibrated_data_max
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        uncalibrated_data_min = line_plot_canvas_item.line_graph_layers_canvas_item._axes.uncalibrated_data_min
        uncalibrated_data_max = line_plot_canvas_item.line_graph_layers_canvas_item._axes.uncalibrated_data_max
        uncalibrated_data_range = uncalibrated_data_max - uncalibrated_data_min
        offset = -uncalibrated_data_range * 30.0 / plot_height
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), calibrated_data_min + offset - intensity_calibration.offset)
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), calibrated_data_max + offset - intensity_calibration.offset)

    def test_mouse_tracking_moves_log_vertical_scale_with_uncalibrated_data(self):
        # notice: dragging increasing y drags down.
        line_plot_canvas_item = self.setup_line_plot(data_min=0.1, data_max=980)
        self.display_item.set_display_property("y_style", "log")
        calibrated_data_min = line_plot_canvas_item.line_graph_layers_canvas_item._axes.calibrated_data_min
        calibrated_data_max = line_plot_canvas_item.line_graph_layers_canvas_item._axes.calibrated_data_max
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        axes = line_plot_canvas_item.line_graph_layers_canvas_item._axes
        calibrated_data_range = calibrated_data_max - calibrated_data_min
        calibrated_offset = -calibrated_data_range * 30.0 / plot_height
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), axes.uncalibrate_y(calibrated_data_min + calibrated_offset))
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), axes.uncalibrate_y(calibrated_data_max + calibrated_offset))

    def test_mouse_tracking_moves_log_vertical_scale_with_calibrated_data_with_offset(self):
        # notice: dragging increasing y drags down.
        line_plot_canvas_item = self.setup_line_plot(data_min=0.1, data_max=980)
        self.display_item.set_display_property("y_style", "log")
        data_item = self.display_item.data_item
        intensity_calibration = data_item.intensity_calibration
        intensity_calibration.offset = 0.2
        data_item.set_intensity_calibration(intensity_calibration)
        calibrated_data_min = line_plot_canvas_item.line_graph_layers_canvas_item._axes.calibrated_data_min
        calibrated_data_max = line_plot_canvas_item.line_graph_layers_canvas_item._axes.calibrated_data_max
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        axes = line_plot_canvas_item.line_graph_layers_canvas_item._axes
        calibrated_data_range = calibrated_data_max - calibrated_data_min
        calibrated_offset = -calibrated_data_range * 30.0 / plot_height
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), axes.uncalibrate_y(calibrated_data_min + calibrated_offset))
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), axes.uncalibrate_y(calibrated_data_max + calibrated_offset))

    def test_mouse_tracking_moves_log_vertical_scale_with_calibrated_data_with_offset_and_scale(self):
        # notice: dragging increasing y drags down.
        line_plot_canvas_item = self.setup_line_plot(data_min=0.1, data_max=980)
        self.display_item.set_display_property("y_style", "log")
        data_item = self.display_item.data_item
        intensity_calibration = data_item.intensity_calibration
        intensity_calibration.offset = 0.2
        intensity_calibration.scale = 1.6
        data_item.set_intensity_calibration(intensity_calibration)
        calibrated_data_min = line_plot_canvas_item.line_graph_layers_canvas_item._axes.calibrated_data_min
        calibrated_data_max = line_plot_canvas_item.line_graph_layers_canvas_item._axes.calibrated_data_max
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        axes = line_plot_canvas_item.line_graph_layers_canvas_item._axes
        calibrated_data_range = calibrated_data_max - calibrated_data_min
        calibrated_offset = -calibrated_data_range * 30.0 / plot_height
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), axes.uncalibrate_y(calibrated_data_min + calibrated_offset))
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), axes.uncalibrate_y(calibrated_data_max + calibrated_offset))

    def test_mouse_tracking_shrink_scale_by_10_around_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=-96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        self.assertEqual(self.display_item.get_display_property("left_channel"), int(round(512 - int(plot_width * 0.5) * 10 * channel_per_pixel)))
        self.assertEqual(self.display_item.get_display_property("right_channel"), int(round(512 + int(plot_width * 0.5) * 10 * channel_per_pixel)))

    def test_mouse_tracking_expand_scale_by_10_around_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        # self.__display.left_channel = int(round(self.__tracking_start_channel - new_drawn_channel_per_pixel * self.__tracking_start_origin_pixel))
        self.assertEqual(self.display_item.get_display_property("left_channel"), int(round(512 - int(plot_width * 0.5) * 0.1 * channel_per_pixel)))
        self.assertEqual(self.display_item.get_display_property("right_channel"), int(round(512 + int(plot_width * 0.5) * 0.1 * channel_per_pixel)))

    def test_mouse_tracking_expand_scale_by_high_amount(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = CanvasItem.KeyboardModifiers(control=True)
        offset = Geometry.IntSize(width=1024, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        drawing_context = DrawingContext.DrawingContext()
        line_plot_canvas_item.repaint_immediate(drawing_context, line_plot_canvas_item.canvas_size)

    def test_mouse_tracking_contract_scale_by_high_amount(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = CanvasItem.KeyboardModifiers(control=True)
        offset = Geometry.IntSize(width=-1024, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        drawing_context = DrawingContext.DrawingContext()
        line_plot_canvas_item.repaint_immediate(drawing_context, line_plot_canvas_item.canvas_size)

    def test_mouse_tracking_expand_scale_by_high_amount_with_interval(self):
        line_plot_canvas_item = self.setup_line_plot()
        interval_graphic = Graphics.IntervalGraphic()
        self.document_model.display_items[1].add_graphic(interval_graphic)
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = CanvasItem.KeyboardModifiers(control=True)
        offset = Geometry.IntSize(width=1024, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        drawing_context = DrawingContext.DrawingContext()
        line_plot_canvas_item.repaint_immediate(drawing_context, line_plot_canvas_item.canvas_size)

    def test_mouse_tracking_contract_scale_by_high_amount_with_interval(self):
        line_plot_canvas_item = self.setup_line_plot()
        interval_graphic = Graphics.IntervalGraphic()
        self.document_model.display_items[1].add_graphic(interval_graphic)
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = CanvasItem.KeyboardModifiers(control=True)
        offset = Geometry.IntSize(width=-1024, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        drawing_context = DrawingContext.DrawingContext()
        line_plot_canvas_item.repaint_immediate(drawing_context, line_plot_canvas_item.canvas_size)

    def test_mouse_tracking_shrink_scale_by_10_around_non_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + 200, y=465)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=-96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        self.assertEqual(self.display_item.get_display_property("left_channel"), int(round(200 * channel_per_pixel - 200 * 10 * channel_per_pixel)))
        self.assertEqual(self.display_item.get_display_property("right_channel"), int(round(200 * channel_per_pixel + (plot_width - 200) * 10 * channel_per_pixel)))

    def test_mouse_tracking_expand_scale_by_10_around_non_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + 400, y=465)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        self.assertEqual(self.display_item.get_display_property("left_channel"), int(round(400 * channel_per_pixel - 400 * 0.1 * channel_per_pixel)))
        self.assertEqual(self.display_item.get_display_property("right_channel"), int(round(400 * channel_per_pixel + (plot_width - 400) * 0.1 * channel_per_pixel)))

    def test_mouse_tracking_vertical_shrink_with_origin_at_bottom(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_bottom = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        pos = Geometry.IntPoint(x=30, y=plot_bottom - 200)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=40)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        scaling = float(plot_bottom - pos.y) / float(plot_bottom - (pos.y + offset.height))
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), 0.0)
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), scaling)

    def test_mouse_tracking_vertical_shrink_with_origin_in_middle(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.display_item.set_display_property("y_min", -0.5)
        self.display_item.set_display_property("y_max", 0.5)
        # now stretch 1/2 + 100 to 1/2 + 150
        pos = Geometry.IntPoint(x=30, y=plot_bottom-320)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=50)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height/2.0) - pos.y
        scaling = float(relative_y) / float(relative_y - offset.height)
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), -0.5 * scaling)
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), 0.5 * scaling)

    def test_mouse_tracking_vertical_shrink_with_origin_at_200(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.display_item.set_display_property("y_min", -0.2)
        self.display_item.set_display_property("y_max", 0.8)
        # now stretch 1/2 + 100 to 1/2 + 150
        pos = Geometry.IntPoint(x=30, y=plot_bottom-320)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=50)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height*0.2) - pos.y
        scaling = float(relative_y) / float(relative_y - offset.height)
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), -0.2 * scaling)
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), 0.8 * scaling)

    def test_mouse_tracking_vertical_shrink_with_calibrated_origin_at_200(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        data_item = self.display_item.data_item
        # adjust image panel display and trigger layout
        intensity_calibration = data_item.intensity_calibration
        intensity_calibration.offset = -0.2
        data_item.set_intensity_calibration(intensity_calibration)
        # now stretch 1/2 + 100 to 1/2 + 150
        pos = Geometry.IntPoint(x=30, y=plot_bottom-320)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=50)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height*0.2) - pos.y
        scaling = float(relative_y) / float(relative_y - offset.height)
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), -0.2 * scaling + 0.2)
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), 0.8 * scaling + 0.2)

    def test_mouse_tracking_vertical_drag_down_does_not_go_negative(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.display_item.set_display_property("y_min", -0.5)
        self.display_item.set_display_property("y_max", 0.5)
        # now stretch way past top
        pos = Geometry.IntPoint(x=30, y=20)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=plot_height)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        new_drawn_data_per_pixel = 1.0/plot_height * (plot_bottom - plot_height*0.5 - pos.y)
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), -new_drawn_data_per_pixel * plot_height*0.5)
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), new_drawn_data_per_pixel * plot_height*0.5)

    def test_mouse_tracking_vertical_drag_up_does_not_go_negative(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.display_item.set_display_property("y_min", -0.5)
        self.display_item.set_display_property("y_max", 0.5)
        # now stretch way past top
        pos = Geometry.IntPoint(x=30, y=plot_height-20)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=-plot_height)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        new_drawn_data_per_pixel = -1.0/plot_height * (plot_bottom - plot_height*0.5 - pos.y)
        self.assertAlmostEqual(self.display_item.get_display_property("y_min"), -new_drawn_data_per_pixel * plot_height*0.5)
        self.assertAlmostEqual(self.display_item.get_display_property("y_max"), new_drawn_data_per_pixel * plot_height*0.5)

    def test_combined_horizontal_drag_and_expand_works_nominally(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        v = line_plot_canvas_item.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)[0] + 8
        line_plot_canvas_item.mouse_pressed(plot_left, v, CanvasItem.KeyboardModifiers(control=True))
        line_plot_canvas_item.mouse_position_changed(plot_left+96, v, CanvasItem.KeyboardModifiers(control=True))
        # continue
        line_plot_canvas_item.mouse_position_changed(plot_left+96, v, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_position_changed(plot_left+196, v, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+116, 190, CanvasItem.KeyboardModifiers())
        self.document_controller.periodic()
        channel_per_pixel = 1024.0/10 / plot_width
        self.assertEqual(self.display_item.get_display_property("left_channel"), int(0 - channel_per_pixel * 100))
        self.assertEqual(self.display_item.get_display_property("right_channel"), int(int(1024/10.0) - channel_per_pixel * 100))

    def test_click_on_selection_makes_it_selected(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_item = self.document_model.get_display_item_for_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        line_plot_display_item.add_graphic(region)
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_display_item.graphic_selection.indexes), 0)
        # do the click
        line_plot_canvas_item.mouse_pressed(plot_left+plot_width * 0.35, 100, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+plot_width * 0.35, 100, CanvasItem.KeyboardModifiers())
        self.document_controller.periodic()
        # make sure results are correct
        self.assertEqual(len(line_plot_display_item.graphic_selection.indexes), 1)

    def test_click_outside_selection_makes_it_unselected(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_item = self.document_model.get_display_item_for_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        line_plot_display_item.add_graphic(region)
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_display_item.graphic_selection.indexes), 0)
        # do the first click to select
        line_plot_canvas_item.mouse_pressed(plot_left+plot_width * 0.35, 100, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+plot_width * 0.35, 100, CanvasItem.KeyboardModifiers())
        self.document_controller.periodic()
        # make sure results are correct
        self.assertEqual(len(line_plot_display_item.graphic_selection.indexes), 1)
        # do the second click to deselect
        line_plot_canvas_item.mouse_pressed(plot_left+plot_width * 0.1, 100, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+plot_width * 0.1, 100, CanvasItem.KeyboardModifiers())
        self.document_controller.periodic()
        # make sure results are correct
        self.assertEqual(len(line_plot_display_item.graphic_selection.indexes), 0)

    def test_click_drag_interval_end_channel_to_right_adjust_end_channel(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_item = self.document_model.get_display_item_for_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        line_plot_display_item.add_graphic(region)
        # select, then click drag
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.35, 100, modifiers)
        self.document_controller.periodic()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.4, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.5, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.5, 100, modifiers)
        self.document_controller.periodic()
        # make sure results are correct
        line_plot_canvas_item.root_container.refresh_layout_immediate()
        self.assertAlmostEqual(line_plot_display_item.graphics[0].start, 0.3)
        self.assertAlmostEqual(line_plot_display_item.graphics[0].end, 0.5)

    def test_click_drag_interval_end_channel_to_left_of_start_channel_results_in_left_less_than_right(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_item = self.document_model.get_display_item_for_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        self.document_model.get_display_item_for_data_item(line_plot_data_item).add_graphic(region)
        # select, then click drag
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.35, 100, modifiers)
        self.document_controller.periodic()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.4, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.2, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.2, 100, modifiers)
        self.document_controller.periodic()
        # make sure results are correct
        self.assertAlmostEqual(line_plot_display_item.graphics[0].start, 0.2, 2)  # pixel accuracy, approx. 1/500
        self.assertAlmostEqual(line_plot_display_item.graphics[0].end, 0.3, 2)  # pixel accuracy, approx. 1/500

    def test_click_drag_interval_tool_creates_selection(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_item = self.document_model.get_display_item_for_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.4
        region.end = 0.6
        self.document_model.get_display_item_for_data_item(line_plot_data_item).add_graphic(region)
        # select, then click drag
        modifiers = CanvasItem.KeyboardModifiers(alt=True)
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.4, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.3, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.3, 100, modifiers)
        self.document_controller.periodic()
        # make sure results are correct
        self.assertAlmostEqual(line_plot_display_item.graphics[0].start, 0.1, 2)  # pixel accuracy, approx. 1/500
        self.assertAlmostEqual(line_plot_display_item.graphics[0].end, 0.9, 2)  # pixel accuracy, approx. 1/500

    def test_click_drag_interval_tool_creates_selection(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_layers_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_item = self.document_model.get_display_item_for_data_item(line_plot_data_item)
        self.document_controller.tool_mode = "interval"
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_display_item.graphics), 0)
        # click drag
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.40, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.50, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.50, 100, modifiers)
        self.document_controller.periodic()
        # make sure results are correct
        self.assertEqual(len(line_plot_display_item.graphics), 1)
        self.assertTrue(isinstance(line_plot_display_item.graphics[0], Graphics.IntervalGraphic))
        self.assertAlmostEqual(line_plot_display_item.graphics[0].start, 0.35, 2)  # pixel accuracy, approx. 1/500
        self.assertAlmostEqual(line_plot_display_item.graphics[0].end, 0.50, 2)  # pixel accuracy, approx. 1/500
        # and that tool is returned to pointer
        self.assertEqual(self.document_controller.tool_mode, "pointer")

    def test_delete_line_profile_with_key(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_layers_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_item = self.document_model.get_display_item_for_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        line_plot_display_item.add_graphic(region)
        line_plot_display_item.graphic_selection.set(0)
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_display_item.graphics), 1)
        self.assertEqual(len(line_plot_display_item.graphic_selection.indexes), 1)
        # hit the delete key
        k = typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("delete")
        self.display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.document_controller.ui).create_key_by_id("delete"))
        self.assertEqual(len(line_plot_display_item.graphics), 0)

    def test_key_gets_dispatched_to_image_canvas_item(self):
        modifiers = CanvasItem.KeyboardModifiers()
        self.display_panel.root_container.canvas_widget.simulate_mouse_click(100, 100, modifiers)
        self.display_panel.root_container.canvas_widget.on_key_pressed(TestUI.Key(None, "up", modifiers))
        self.display_panel.display_canvas_item.scroll_area_canvas_item.refresh_layout_immediate()
        self.assertEqual(self.display_panel.display_canvas_item.scroll_area_canvas_item.canvas_items[0].canvas_rect, ((-10, 0), (1000, 1000)))

    def test_drop_on_overlay_middle_triggers_replace_data_item_in_panel_action(self):
        width, height = 640, 480
        display_panel = TestDisplayPanel()
        def get_font_metrics(a, b): return UserInterface.FontMetrics(0, 0, 0, 0, 0)
        overlay = DisplayPanel.DisplayPanelOverlayCanvasItem(get_font_metrics)
        overlay.on_drag_enter = display_panel.handle_drag_enter
        overlay.on_drag_move = display_panel.handle_drag_move
        overlay.on_drop = display_panel.handle_drop
        overlay.update_layout((0, 0), (height, width))
        mime_data = None
        overlay.drag_enter(mime_data)
        overlay.drag_move(mime_data, int(width*0.5), int(height*0.5))
        overlay.drop(mime_data, int(width*0.5), int(height*0.5))
        self.assertEqual(display_panel.drop_region, "middle")

    def test_replacing_display_actually_does_it(self):
        self.assertEqual(self.display_panel.data_item, self.data_item)
        self.display_panel.set_display_panel_display_item(self.display_item)
        data_item_1d = DataItem.DataItem(create_1d_data())
        self.document_model.append_data_item(data_item_1d)
        display_item_1d = self.document_model.get_display_item_for_data_item(data_item_1d)
        self.display_panel.set_display_panel_display_item(display_item_1d)
        self.assertEqual(self.display_panel.data_item, data_item_1d)

    def test_drop_on_overlay_edge_triggers_split_image_panel_action(self):
        width, height = 640, 480
        display_panel = TestDisplayPanel()
        def get_font_metrics(a, b): return UserInterface.FontMetrics(0, 0, 0, 0, 0)
        overlay = DisplayPanel.DisplayPanelOverlayCanvasItem(get_font_metrics)
        overlay.on_drag_enter = display_panel.handle_drag_enter
        overlay.on_drag_move = display_panel.handle_drag_move
        overlay.on_drop = display_panel.handle_drop
        overlay.update_layout((0, 0), (height, width))
        mime_data = None
        overlay.drag_enter(mime_data)
        overlay.drag_move(mime_data, int(width*0.05), int(height*0.5))
        overlay.drop(mime_data, int(width*0.05), int(height*0.5))
        self.assertEqual(display_panel.drop_region, "left")

    def test_replace_displayed_display_item_and_display_detects_default_raster_display(self):
        self.display_panel.set_display_panel_display_item(self.display_item)
        self.assertEqual(self.display_panel.data_item, self.data_item)

    def test_1d_data_with_zero_dimensions_display_fails_without_exception(self):
        self.data_item.set_data(numpy.zeros((0, )))
        # display panel should not have any display_canvas_item now since data is not valid
        self.assertIsInstance(self.display_panel.display_canvas_item, DisplayPanel.MissingDataCanvasItem)
        # thumbnails and processors
        thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.document_controller.ui, self.display_item)
        with thumbnail_source.ref():
            thumbnail_source.recompute_data()
            self.assertIsNotNone(thumbnail_source.thumbnail_data)
        self.document_controller.periodic()
        self.document_controller.document_model.recompute_all()

    def test_2d_data_with_zero_dimensions_display_fails_without_exception(self):
        self.data_item.set_data(numpy.zeros((0, 0)))
        # display panel should not have any display_canvas_item now since data is not valid
        self.assertIsInstance(self.display_panel.display_canvas_item, DisplayPanel.MissingDataCanvasItem)
        # thumbnails and processors
        thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.document_controller.ui, self.display_item)
        with thumbnail_source.ref():
            thumbnail_source.recompute_data()
        self.document_controller.periodic()
        self.document_controller.document_model.recompute_all()

    def test_perform_action_gets_dispatched_to_image_canvas_item(self):
        self.assertEqual(self.display_panel.display_canvas_item.image_canvas_mode, "fit")
        self.display_panel.perform_action("set_fill_mode")
        self.assertEqual(self.display_panel.display_canvas_item.image_canvas_mode, "fill")

    def test_dragging_to_add_point_makes_desired_point(self):
        self.document_controller.tool_mode = "point"
        self.display_panel.display_canvas_item.simulate_drag((100,125), (200,250))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphics), 1)
        region = self.display_item.graphics[0]
        self.assertEqual(region.type, "point-graphic")
        self.assertAlmostEqual(region.position[0], 0.2)
        self.assertAlmostEqual(region.position[1], 0.25)

    def test_dragging_to_add_rectangle_makes_desired_rectangle(self):
        self.document_controller.tool_mode = "rectangle"
        self.display_panel.display_canvas_item.simulate_drag((100,125), (250,200))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphics), 1)
        region = self.display_item.graphics[0]
        self.assertEqual(region.type, "rect-graphic")
        self.assertAlmostEqual(region.bounds[0][0], 0.1)
        self.assertAlmostEqual(region.bounds[0][1], 0.125)
        self.assertAlmostEqual(region.bounds[1][0], 0.15)
        self.assertAlmostEqual(region.bounds[1][1], 0.075)

    def test_dragging_to_add_ellipse_makes_desired_ellipse(self):
        self.document_controller.tool_mode = "ellipse"
        self.display_panel.display_canvas_item.simulate_drag((100,125), (250,200))
        self.document_controller.periodic()
        self.assertEqual(len(self.display_item.graphics), 1)
        region = self.display_item.graphics[0]
        self.assertEqual(region.type, "ellipse-graphic")
        self.assertAlmostEqual(region.bounds[0][0], 0.1 - 0.30 / 2)
        self.assertAlmostEqual(region.bounds[0][1], 0.125 - 0.15 / 2)
        self.assertAlmostEqual(region.bounds[1][0], 0.30)
        self.assertAlmostEqual(region.bounds[1][1], 0.15)

    def test_dragging_to_add_line_makes_desired_line_and_is_undoable(self):
        with TestContext.create_memory_context() as test_context:
            # set up the layout
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.workspace_controller.display_panels[0]
            document_controller.tool_mode = "line"
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            header_height = self.display_panel.header_canvas_item.header_height
            root_canvas_item.update_layout(Geometry.IntPoint(), Geometry.IntSize(width=1000, height=1000 + header_height))
            # drag to make line
            display_panel.display_canvas_item.simulate_drag((100,125), (200,250))
            document_controller.periodic()
            self.assertEqual(1, len(display_item.graphics))
            region = display_item.graphics[0]
            self.assertEqual("line-graphic", region.type)
            self.assertAlmostEqual(0.1, region.start[0])
            self.assertAlmostEqual(0.125, region.start[1])
            self.assertAlmostEqual(0.2, region.end[0])
            self.assertAlmostEqual(0.25, region.end[1])
            # check undo/redo
            document_controller.handle_undo()
            self.assertEqual(0, len(display_item.graphics))
            document_controller.handle_redo()
            self.assertEqual(1, len(display_item.graphics))

    def test_dragging_to_add_line_profile_makes_desired_line_profile(self):
        with TestContext.create_memory_context() as test_context:
            # set up the layout
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.workspace_controller.display_panels[0]
            document_controller.tool_mode = "line-profile"
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            header_height = self.display_panel.header_canvas_item.header_height
            root_canvas_item.update_layout(Geometry.IntPoint(), Geometry.IntSize(width=1000, height=1000 + header_height))
            # drag for the line profile
            display_panel.display_canvas_item.simulate_drag((100,125), (200,250))
            self.document_controller.periodic()
            # check results
            self.assertEqual(len(display_item.graphics), 1)
            region = display_item.graphics[0]
            self.assertEqual(region.type, "line-profile-graphic")
            self.assertAlmostEqual(region.start[0], 0.1)
            self.assertAlmostEqual(region.start[1], 0.125)
            self.assertAlmostEqual(region.end[0], 0.2)
            self.assertAlmostEqual(region.end[1], 0.25)

    def test_dragging_to_add_line_profile_puts_source_and_destination_under_transaction(self):
        with TestContext.create_memory_context() as test_context:
            # set up the layout
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.workspace_controller.display_panels[0]
            document_controller.tool_mode = "line-profile"
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            header_height = self.display_panel.header_canvas_item.header_height
            root_canvas_item.update_layout(Geometry.IntPoint(), Geometry.IntSize(width=1000, height=1000 + header_height))
            # drag and check transactions
            self.assertFalse(data_item.in_transaction_state)
            self.assertFalse(display_item.in_transaction_state)
            modifiers = CanvasItem.KeyboardModifiers()
            display_panel.display_canvas_item.mouse_pressed(100, 100, modifiers)
            display_panel.display_canvas_item.mouse_position_changed(125, 125, modifiers)
            document_controller.periodic()
            self.assertTrue(data_item.in_transaction_state)
            self.assertTrue(display_item.in_transaction_state)
            line_plot_data_item = document_model.data_items[-1]
            line_plot_display_item = document_model.display_items[-1]
            self.assertTrue(line_plot_data_item.in_transaction_state)
            self.assertTrue(line_plot_display_item.in_transaction_state)
            display_panel.display_canvas_item.mouse_released(200, 200, modifiers)
            document_controller.periodic()
            self.assertFalse(data_item.in_transaction_state)
            self.assertFalse(display_item.in_transaction_state)
            self.assertFalse(line_plot_data_item.in_transaction_state)
            self.assertFalse(line_plot_display_item.in_transaction_state)

    def test_dragging_to_add_line_profile_works_when_line_profile_is_filtered_from_data_panel(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            d = {"type": "splitter", "orientation": "vertical", "splits": [0.5, 0.5], "children": [
                {"type": "image", "uuid": "0569ca31-afd7-48bd-ad54-5e2bb9f21102", "identifier": "a", "selected": True},
                {"type": "image", "uuid": "acd77f9f-2f6f-4fbf-af5e-94330b73b997", "identifier": "b"}]}
            workspace_2x1 = document_controller.workspace_controller.new_workspace("2x1", d)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            header_height = self.display_panel.header_canvas_item.header_height
            display_panel = document_controller.workspace_controller.display_panels[0]
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            self.assertIsNotNone(display_panel.display_canvas_item)
            root_canvas_item.update_layout(Geometry.IntPoint(), Geometry.IntSize(width=1000, height=500 + header_height))
            document_controller.set_filter("none")
            document_controller.tool_mode = "line-profile"
            display_panel.display_canvas_item.simulate_drag((100,125), (200,250))
            self.document_controller.periodic()
            self.assertEqual(len(display_item.graphics), 1)
            region = display_item.graphics[0]
            self.assertEqual(region.type, "line-profile-graphic")
            self.assertAlmostEqual(0.2, region.start[0])
            self.assertAlmostEqual(0.25, region.start[1])
            self.assertAlmostEqual(0.4, region.end[0])
            self.assertAlmostEqual(0.5, region.end[1])

    def test_enter_to_auto_display_limits(self):
        # test preliminary assumptions (no display limits)
        display_limits = 0.5, 1.5
        display_data_channel = self.display_item.display_data_channels[0]
        display_data_channel.display_limits = display_limits
        self.assertIsNotNone(display_data_channel.display_limits)
        # focus on the display panel, then press the enter key
        modifiers = CanvasItem.KeyboardModifiers()
        self.display_panel.root_container.canvas_widget.simulate_mouse_click(100, 100, modifiers)
        self.display_panel.root_container.canvas_widget.on_key_pressed(TestUI.Key(None, "enter", modifiers))
        # confirm that display limits were set
        self.assertIsNotNone(display_data_channel.display_limits)
        self.assertNotEqual(display_data_channel.display_limits, display_limits)

    def test_image_display_panel_produces_context_menu_with_correct_item_count(self):
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.canvas_widget.on_context_menu_event(500, 500, 500, 500)
        # show, sep, delete, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(20, len(self.document_controller.ui.popup.items))

    def test_image_display_panel_produces_context_menu_with_correct_item_count_outside_image_area(self):
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.canvas_widget.on_context_menu_event(10, 32, 10, 32)  # header + 10
        # show, sep, delete, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(20, len(self.document_controller.ui.popup.items))

    def test_image_display_panel_with_no_image_produces_context_menu_with_correct_item_count(self):
        self.display_panel.set_display_panel_display_item(None)
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(500, 500, 500, 500)
        # reveal, export, sep, del, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(14, len(self.document_controller.ui.popup.items))

    def test_empty_display_panel_produces_context_menu_with_correct_item_count(self):
        d = {"type": "image", "display-panel-type": "empty-display-panel"}
        self.display_panel.change_display_panel_content(d)
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(500, 500, 500, 500)
        # reveal, export, sep, del, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(14, len(self.document_controller.ui.popup.items))

    def test_browser_display_panel_produces_context_menu_with_correct_item_count_over_data_item(self):
        d = {"type": "image", "display-panel-type": "browser-display-panel"}
        self.display_panel.change_display_panel_content(d)
        self.document_controller.periodic()
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(40, 40, 40, 40)
        # show, sep, delete, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(20, len(self.document_controller.ui.popup.items))

    def test_browser_display_panel_produces_context_menu_with_correct_item_count_over_area_to_right_of_data_item(self):
        d = {"type": "image", "display-panel-type": "browser-display-panel"}
        self.display_panel.change_display_panel_content(d)
        self.document_controller.periodic()
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(300, 40, 300, 40)
        # reveal, export, sep, del, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(14, len(self.document_controller.ui.popup.items))

    def test_browser_display_panel_produces_context_menu_with_correct_item_count_below_last_data_item(self):
        d = {"type": "image", "display-panel-type": "browser-display-panel"}
        self.display_panel.change_display_panel_content(d)
        self.document_controller.periodic()
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(300, 300, 300, 300)
        # reveal, export, sep, del, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(14, len(self.document_controller.ui.popup.items))

    def test_browser_context_menu_deletes_all_selected_items(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.ones((8, 8), float))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            d = {"type": "image", "display-panel-type": "browser-display-panel"}
            display_panel.change_display_panel_content(d)
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            self.assertEqual(len(document_model.data_items), 4)
            self.assertIsNone(document_controller.ui.popup)
            self.assertEqual(display_panel, document_controller.selected_display_panel)
            display_panel._selection_for_test.add_range(range(0, 4))
            display_panel.root_container.refresh_layout_immediate()
            display_panel.root_container.canvas_widget.on_context_menu_event(40, 40, 40, 40)
            document_controller.periodic()
            # reveal, export, sep, delete, sep, split h, split v, sep, clear, sep, display, thumbnail, grid, sep
            delete_item = next(x for x in document_controller.ui.popup.items if x.title.startswith("Delete Display Items"))
            delete_item.callback()
            document_controller.periodic()
            self.assertEqual(0, len(document_model.data_items))

    def test_display_panel_title_gets_updated_when_data_item_title_is_changed(self):
        self.assertEqual(self.display_panel.header_canvas_item.title, self.display_item.displayed_title)
        self.data_item.title = "New Title"
        self.assertEqual(self.display_panel.header_canvas_item.title, self.display_item.displayed_title)

    def test_display_panel_title_gets_updated_when_data_item_r_value_is_changed(self):
        self.assertEqual(self.display_panel.header_canvas_item.title, self.display_item.displayed_title)
        DocumentModel.MappedItemManager().register(self.document_model, self.display_item)
        self.assertNotEqual(self.display_panel.header_canvas_item.title, self.display_item.displayed_title)

    def test_all_graphic_types_repaint_on_1d_display(self):
        display_canvas_item = self.setup_line_plot()
        self.document_controller.add_point_graphic()
        self.document_controller.add_line_graphic()
        self.document_controller.add_rectangle_graphic()
        self.document_controller.add_ellipse_graphic()
        self.document_controller.add_interval_graphic()
        drawing_context = DrawingContext.DrawingContext()
        display_canvas_item.repaint_immediate(drawing_context, display_canvas_item.canvas_size)

    def test_all_graphic_types_repaint_on_2d_display(self):
        self.document_controller.add_point_graphic()
        self.document_controller.add_line_graphic()
        self.document_controller.add_rectangle_graphic()
        self.document_controller.add_ellipse_graphic()
        self.document_controller.add_interval_graphic()
        drawing_context = DrawingContext.DrawingContext()
        self.display_panel.display_canvas_item.repaint_immediate(drawing_context, self.display_panel.display_canvas_item.canvas_size)

    def test_all_graphic_types_repaint_on_3d_display(self):
        display_canvas_item = self.setup_3d_data()
        self.document_controller.add_point_graphic()
        self.document_controller.add_line_graphic()
        self.document_controller.add_rectangle_graphic()
        self.document_controller.add_ellipse_graphic()
        self.document_controller.add_interval_graphic()
        drawing_context = DrawingContext.DrawingContext()
        display_canvas_item.repaint_immediate(drawing_context, display_canvas_item.canvas_size)

    def test_all_graphic_types_hit_test_on_1d_display(self):
        display_canvas_item = self.setup_line_plot()
        self.document_controller.add_point_graphic()
        self.document_controller.add_line_graphic()
        self.document_controller.add_rectangle_graphic()
        self.document_controller.add_ellipse_graphic()
        self.document_controller.add_interval_graphic()
        display_canvas_item.mouse_pressed(100, 100, CanvasItem.KeyboardModifiers())
        display_canvas_item.mouse_released(100, 100, CanvasItem.KeyboardModifiers())
        self.document_controller.periodic()

    def test_all_graphic_types_hit_test_on_2d_display(self):
        self.document_controller.add_point_graphic()
        self.document_controller.add_line_graphic()
        self.document_controller.add_rectangle_graphic()
        self.document_controller.add_ellipse_graphic()
        self.document_controller.add_interval_graphic()
        self.display_panel.display_canvas_item.mouse_pressed(10, 10, CanvasItem.KeyboardModifiers())
        self.display_panel.display_canvas_item.mouse_released(10, 10, CanvasItem.KeyboardModifiers())
        self.document_controller.periodic()

    def test_all_graphic_types_hit_test_on_3d_display(self):
        display_canvas_item = self.setup_3d_data()
        self.document_controller.add_point_graphic()
        self.document_controller.add_line_graphic()
        self.document_controller.add_rectangle_graphic()
        self.document_controller.add_ellipse_graphic()
        self.document_controller.add_interval_graphic()
        display_canvas_item.mouse_pressed(10, 10, CanvasItem.KeyboardModifiers())
        display_canvas_item.mouse_released(10, 10, CanvasItem.KeyboardModifiers())
        self.document_controller.periodic()

    def test_display_graphics_update_after_changing_display_type(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.ones((8, 8), float))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            document_controller.periodic()
            display_item.display_type = "line_plot"
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            document_controller.periodic()
            display_item.display_type = "image"
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            document_controller.periodic()
            display_item.display_type = None
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            document_controller.periodic()
            display_panel._handle_key_pressed(TestUI.Key(None, "up", None))

    def test_display_2d_updates_display_values_after_changing_display_type(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            document_controller.periodic()
            data_item = DataItem.DataItem(numpy.ones((8, 8), float))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            display_item.display_type = "line_plot"
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            display_item.display_type = "image"
            self.assertIsNotNone(display_panel.display_canvas_item._display_values)

    def test_display_2d_update_with_no_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item1 = DataItem.DataItem(numpy.ones((8, 8), float))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item = document_model.get_crop_new(display_item1, display_item1.data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            document_controller.periodic()

    def test_display_2d_collection_with_2d_datum_displays_image(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem()
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(numpy.ones((2, 2, 8, 8)), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)

    def test_image_display_canvas_item_only_updates_if_display_data_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 240))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)
            update_count = display_panel.display_canvas_item._update_count
            document_controller.periodic()
            self.assertEqual(update_count, display_panel.display_canvas_item._update_count)

    def test_image_display_canvas_item_only_updates_once_if_data_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(240, 640))
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)
            update_count = display_panel.display_canvas_item._update_count
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(numpy.random.randn(8, 8)))
            self.assertEqual(update_count + 1, display_panel.display_canvas_item._update_count)

    def test_image_display_canvas_item_only_updates_once_if_graphic_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            graphic = Graphics.RectangleGraphic()
            display_item.add_graphic(graphic)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 240))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)
            update_count = display_panel.display_canvas_item._update_count
            graphic.bounds = Geometry.FloatRect.from_tlbr(0.1, 0.1, 0.2, 0.2)
            self.assertEqual(update_count + 1, display_panel.display_canvas_item._update_count)

    def test_image_display_canvas_item_does_not_update_if_graphic_does_not_change(self):
        # confirm that clicking on a graphic does not change the display item (causing it or its thumbnail to redraw).
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            graphic = Graphics.RectangleGraphic()
            display_item.add_graphic(graphic)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 240))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)
            document_controller.periodic()
            # click once
            display_panel.display_canvas_item.simulate_click(Geometry.IntPoint(120, 120))
            document_controller.periodic()
            update_count = display_panel.display_canvas_item._update_count

            display_item_did_change = False

            def item_changed() -> None:
                nonlocal display_item_did_change
                display_item_did_change = True

            with display_item.item_changed_event.listen(item_changed):
                # click again, nothing should change. use explicit press/release to perform periodic.
                display_panel.display_canvas_item.simulate_press(Geometry.IntPoint(120, 120))
                document_controller.periodic()
                display_panel.display_canvas_item.simulate_release(Geometry.IntPoint(120, 120))
                document_controller.periodic()
                self.assertEqual(update_count, display_panel.display_canvas_item._update_count)

            self.assertFalse(display_item_did_change)

    def test_image_display_canvas_item_only_updates_once_if_color_map_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_data_channel = display_item.display_data_channels[0]
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(240, 640))
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)
            update_count = display_panel.display_canvas_item._update_count
            display_data_channel.color_map_id = "hsv"
            self.assertEqual(update_count + 1, display_panel.display_canvas_item._update_count)

    def test_line_plot_image_display_canvas_item_only_updates_if_display_data_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 640))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)
            update_count = display_panel.display_canvas_item._update_count
            document_controller.periodic()
            self.display_panel.root_container.refresh_layout_immediate()
            self.assertEqual(update_count, display_panel.display_canvas_item._update_count)

    def test_focused_data_item_changes_when_display_changed_directly_in_content(self):
        # this capability is only used in the camera plug-in when switching image to summed and back.
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item2 = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item2)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            self.assertEqual(data_item, document_controller.selected_data_item)
            display_panel._select()
            self.assertEqual(data_item, document_controller.selected_data_item)
            display_panel.set_display_item(document_model.get_display_item_for_data_item(data_item2))
            self.assertEqual(data_item2, document_controller.selected_data_item)

    def test_dependency_icons_updated_properly_when_one_of_two_dependents_are_removed(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            document_model.get_crop_new(display_item, display_item.data_item)
            document_model.get_line_profile_new(display_item, display_item.data_item)
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(display_item.graphics))
            self.assertEqual(2, len(document_model.get_dependent_items(data_item)))
            display_panel.set_display_panel_display_item(display_item)
            self.assertEqual(2, len(display_panel._related_icons_canvas_item._dependent_thumbnails.canvas_items))
            display_item.remove_graphic(display_item.graphics[1]).close()
            self.assertEqual(1, len(display_panel._related_icons_canvas_item._dependent_thumbnails.canvas_items))

    def test_dragging_to_create_interval_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 640))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            self.assertEqual(0, len(display_item.graphics))
            self.assertIsInstance(display_panel.display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)
            line_plot_canvas_item = display_panel.display_canvas_item
            line_plot_canvas_item._mouse_dragged(0.35, 0.55)
            # check the undo status
            self.assertEqual(1, len(display_item.graphics))
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            for i in range(2):
                # try the undo
                document_controller.handle_undo()
                self.assertEqual(0, len(display_item.graphics))
                self.assertFalse(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the redo
                document_controller.handle_redo()
                self.assertEqual(1, len(display_item.graphics))
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertFalse(document_controller._undo_stack.can_redo)

    def test_dragging_to_change_interval_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            interval_graphic = Graphics.IntervalGraphic()
            interval_graphic.start = 0.3
            interval_graphic.end = 0.5
            display_item.add_graphic(interval_graphic)
            display_item.graphic_selection.set(0)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            self.assertEqual(1, len(display_item.graphics))
            self.assertIsInstance(display_panel.display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)
            line_plot_canvas_item = display_panel.display_canvas_item
            line_plot_canvas_item._mouse_dragged(0.4, 0.5)
            # check the undo status. use full object specifiers since objects may be replaced.
            self.assertEqual(1, len(display_item.graphics))
            self.assertAlmostEqual(0.4, display_item.graphics[0].interval[0], 1)
            self.assertAlmostEqual(0.6, display_item.graphics[0].interval[1], 1)
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            for i in range(2):
                # try the undo
                document_controller.handle_undo()
                self.assertEqual(1, len(display_item.graphics))
                self.assertAlmostEqual(0.3, display_item.graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.5, display_item.graphics[0].interval[1], 1)
                self.assertFalse(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the redo
                document_controller.handle_redo()
                self.assertEqual(1, len(display_item.graphics))
                self.assertAlmostEqual(0.4, display_item.graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.6, display_item.graphics[0].interval[1], 1)
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertFalse(document_controller._undo_stack.can_redo)

    def test_display_undo_invalidated_with_external_change(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            interval_graphic = Graphics.IntervalGraphic()
            interval_graphic.start = 0.3
            interval_graphic.end = 0.5
            display_item.add_graphic(interval_graphic)
            display_item.graphic_selection.set(0)
            self.assertEqual(1, len(display_item.graphics))
            command = DisplayPanel.ChangeGraphicsCommand(document_model, display_item, [interval_graphic])
            display_item.graphics[0].interval = 0.4, 0.6
            document_controller.push_undo_command(command)
            # check the undo status. use full object specifiers since objects may be replaced.
            self.assertEqual(1, len(display_item.graphics))
            self.assertAlmostEqual(0.4, display_item.graphics[0].interval[0], 1)
            self.assertAlmostEqual(0.6, display_item.graphics[0].interval[1], 1)
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            # external change
            display_item.graphics[0].interval = (0.3, 0.5)
            document_controller._undo_stack.validate()
            self.assertFalse(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            # make another change, make sure stack is cleared
            command = DisplayPanel.ChangeGraphicsCommand(document_model, display_item, [interval_graphic])
            display_item.graphics[0].interval = 0.4, 0.6
            document_controller.push_undo_command(command)
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            self.assertEqual(1, document_controller._undo_stack._undo_count)
            self.assertEqual(0, document_controller._undo_stack._redo_count)

    def test_dragging_to_create_and_change_interval_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            self.assertEqual(0, len(display_item.graphics))
            self.assertIsInstance(display_panel.display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)
            line_plot_canvas_item = display_panel.display_canvas_item
            line_plot_canvas_item._mouse_dragged(0.3, 0.5)
            self.assertEqual(1, len(display_item.graphics))
            self.assertAlmostEqual(0.3, display_item.graphics[0].interval[0], 1)
            self.assertAlmostEqual(0.5, display_item.graphics[0].interval[1], 1)
            line_plot_canvas_item._mouse_dragged(0.4, 0.5)
            # check the undo status. use full object specifiers since objects may be replaced.
            self.assertEqual(1, len(display_item.graphics))
            self.assertAlmostEqual(0.4, display_item.graphics[0].interval[0], 1)
            self.assertAlmostEqual(0.6, display_item.graphics[0].interval[1], 1)
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            for i in range(2):
                # try the first undo
                document_controller.handle_undo()
                self.assertEqual(1, len(display_item.graphics))
                self.assertAlmostEqual(0.3, display_item.graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.5, display_item.graphics[0].interval[1], 1)
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the second undo
                document_controller.handle_undo()
                self.assertEqual(0, len(display_item.graphics))
                self.assertFalse(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the first redo
                document_controller.handle_redo()
                self.assertEqual(1, len(display_item.graphics))
                self.assertAlmostEqual(0.3, display_item.graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.5, display_item.graphics[0].interval[1], 1)
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the second redo
                document_controller.handle_redo()
                self.assertEqual(1, len(display_item.graphics))
                self.assertAlmostEqual(0.4, display_item.graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.6, display_item.graphics[0].interval[1], 1)
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertFalse(document_controller._undo_stack.can_redo)

    def test_display_undo_display_changes_command_merges_repeated_commands(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.set_display_property("y_min", 0.0)
            display_item.set_display_property("y_max", 5.0)
            y_min = display_item.get_display_property("y_min")
            y_max = display_item.get_display_property("y_max")
            for i in range(3):
                command = DisplayPanel.ChangeDisplayCommand(document_controller.document_model, display_item, command_id="y", is_mergeable=True)
                display_item.set_display_property("y_min", display_item.get_display_property("y_min") + 1)
                display_item.set_display_property("y_max", display_item.get_display_property("y_max") + 1)
                document_controller.push_undo_command(command)
                self.assertEqual(1, document_controller._undo_stack._undo_count)
            document_controller.handle_undo()
            self.assertEqual(0, document_controller._undo_stack._undo_count)
            self.assertEqual(y_min, display_item.get_display_property("y_min"))
            self.assertEqual(y_max, display_item.get_display_property("y_max"))

    def test_remove_graphics_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            interval_graphic1 = Graphics.IntervalGraphic()
            interval_graphic1.start = 0.1
            interval_graphic1.end = 0.4
            interval_graphic2 = Graphics.IntervalGraphic()
            interval_graphic2.start = 0.6
            interval_graphic2.end = 0.9
            display_item.add_graphic(interval_graphic1)
            display_item.add_graphic(interval_graphic2)
            display_item.graphic_selection.set(0)
            display_item.graphic_selection.add(1)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            # verify setup
            self.assertEqual(2, len(display_item.graphics))
            # do the delete
            document_controller.remove_selected_graphics()
            self.assertEqual(0, len(display_item.graphics))
            # do the undo and verify
            document_controller.handle_undo()
            self.assertEqual(2, len(display_item.graphics))
            # do the redo and verify
            document_controller.handle_redo()
            self.assertEqual(0, len(display_item.graphics))

    def test_remove_graphics_with_dependent_data_item_display_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_plot_data_item = document_model.get_line_profile_new(display_item, display_item.data_item)
            line_plot_display_item = document_model.get_display_item_for_data_item(line_plot_data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(line_plot_display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            # verify setup
            self.assertEqual(1, len(display_item.graphics))
            self.assertEqual(line_plot_data_item, display_panel.data_item)
            # do the delete
            command = document_controller.create_remove_graphics_command(display_item, display_item.graphics)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(0, len(display_item.graphics))
            self.assertEqual(None, display_panel.data_item)
            # do the undo and verify
            document_controller.handle_undo()
            line_plot_data_item = document_model.data_items[1]
            self.assertEqual(1, len(display_item.graphics))
            self.assertEqual(line_plot_data_item, display_panel.data_item)
            # do the redo and verify
            document_controller.handle_redo()
            self.assertEqual(0, len(display_item.graphics))
            self.assertEqual(None, display_panel.data_item)

    def test_remove_data_item_with_dependent_data_item_display_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_plot_data_item = document_model.get_line_profile_new(display_item, display_item.data_item)
            line_plot_display_item = document_model.get_display_item_for_data_item(line_plot_data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(line_plot_display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            # verify setup
            self.assertEqual(1, len(display_item.graphics))
            self.assertEqual(line_plot_data_item, display_panel.data_item)
            # do the delete
            command = document_controller.create_remove_data_items_command([line_plot_data_item])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(0, len(display_item.graphics))
            self.assertEqual(None, display_panel.data_item)
            # do the undo and verify
            document_controller.handle_undo()
            line_plot_data_item = document_model.data_items[1]
            self.assertEqual(1, len(display_item.graphics))
            self.assertEqual(line_plot_data_item, display_panel.data_item)
            # do the redo and verify
            document_controller.handle_redo()
            self.assertEqual(0, len(display_item.graphics))
            self.assertEqual(None, display_panel.data_item)

    def test_line_plot_with_two_data_items_interval_inspector(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((32, )))
            data_item2 = DataItem.DataItem(numpy.zeros((32, )))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            line_plot_canvas_item = display_panel.display_canvas_item
            line_plot_canvas_item._mouse_dragged(0.3, 0.5)

    def test_removing_interval_from_line_plot_with_two_data_items_succeeds(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((32, )))
            data_item2 = DataItem.DataItem(numpy.zeros((32, )))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
            interval_graphic = Graphics.IntervalGraphic()
            display_item.add_graphic(interval_graphic)
            display_item.graphic_selection.add(0)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.remove_selected_graphics()

    def test_image_data_from_processing_initially_displays(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            fft_data_item = document_model.get_fft_new(display_item, display_item.data_item)
            display_panel.set_display_panel_display_item(document_model.get_display_item_for_data_item(fft_data_item))
            document_model.recompute_all()
            display_panel.root_container.layout_immediate(Geometry.IntSize(200, 200))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            # everything should be updated; the display values should not be dirty
            self.assertIsNotNone(display_panel.display_canvas_item._display_values)
            self.assertFalse(display_panel.display_canvas_item._display_values_dirty)

    def test_line_plot_data_from_processing_initially_displays(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            line_profile_data_item = document_model.get_line_profile_new(display_item, display_item.data_item)
            display_panel.set_display_panel_display_item(document_model.get_display_item_for_data_item(line_profile_data_item))
            document_model.recompute_all()
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000, 200))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            # everything should be updated; the display values should not be dirty
            self.assertTrue(display_panel.display_canvas_item._has_valid_drawn_graph_data)

    def test_line_plot_data_displays_after_delete_then_undo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, )))
            data_item.dimensional_calibrations = [Calibration.Calibration(units="miles")]
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000, 200))
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            command = document_controller.create_remove_display_items_command([display_item])
            command.perform()
            document_controller.push_undo_command(command)
            # undo and check
            document_controller.handle_undo()
            # everything should be updated; the display values should not be dirty
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000, 200))
            display_panel.display_canvas_item.refresh_layout_immediate()
            self.assertTrue(display_panel.display_canvas_item._has_valid_drawn_graph_data)

    def test_image_and_line_plot_produce_svg(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.ones((10, )))
            document_model.append_data_item(data_item2)
            # check svg
            self.assertIsNotNone(Facade.DataItem(data_item1).data_item_to_svg())
            self.assertIsNotNone(Facade.DataItem(data_item2).data_item_to_svg())
            # also check with more than one display
            document_model.get_display_item_copy_new(document_model.get_display_item_for_data_item(data_item1))
            document_model.get_display_item_copy_new(document_model.get_display_item_for_data_item(data_item2))
            self.assertIsNotNone(Facade.DataItem(data_item1).data_item_to_svg())
            self.assertIsNotNone(Facade.DataItem(data_item2).data_item_to_svg())

    def test_line_plot_display_item_with_missing_data_item_fails_gracefully(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item1 = DataItem.DataItem(numpy.ones((2,)))
                document_model.append_data_item(data_item1)
                data_item2 = DataItem.DataItem(numpy.ones((2,)))
                document_model.append_data_item(data_item2)
                display_item = DisplayItem.DisplayItem()
                document_model.append_display_item(display_item)
                display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item1))
                display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
                display_panel = document_controller.selected_display_panel
                display_panel.set_display_panel_display_item(display_item)
                display_panel.root_container.layout_immediate(Geometry.IntSize(200, 200))
                display_panel.display_canvas_item.refresh_layout_immediate()
            profile_context.project_properties["display_items"][2]["display_data_channels"][0]["data_item_reference"] = str(uuid.uuid4())
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                display_panel = document_controller.selected_display_panel
                display_panel.root_container.layout_immediate(Geometry.IntSize(200, 200))
                display_panel.display_canvas_item.refresh_layout_immediate()

    def test_image_display_item_with_missing_data_item_fails_gracefully(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item1 = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item1)
                data_item2 = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item2)
                display_item = DisplayItem.DisplayItem()
                document_model.append_display_item(display_item)
                display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item1))
                display_item.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2))
                display_panel = document_controller.selected_display_panel
                display_panel.set_display_panel_display_item(display_item)
                display_panel.root_container.layout_immediate(Geometry.IntSize(200, 200))
                display_panel.display_canvas_item.refresh_layout_immediate()
            profile_context.project_properties["display_items"][2]["display_data_channels"][0]["data_item_reference"] = str(uuid.uuid4())
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                display_panel = document_controller.selected_display_panel
                display_panel.root_container.layout_immediate(Geometry.IntSize(200, 200))
                display_panel.display_canvas_item.refresh_layout_immediate()

    def test_append_display_data_channel_undo_redo_cycle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item._set_display_layer_property(0, "label", "A")
            # check assumptions
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(1, len(display_item.data_items))
            self.assertEqual(1, len(display_item.display_layers))
            # perform command
            command = DisplayPanel.AppendDisplayDataChannelCommand(document_model, display_item, data_item2, DisplayItem.display_layer_factory(typing.cast(typing.Any, None)))
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(2, len(display_item.data_items))
            self.assertEqual(2, len(display_item.display_layers))
            new_fill_color = display_item.get_display_layer_property(1, "fill_color")
            # try the undo
            document_controller.handle_undo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(1, len(display_item.data_items))
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual("A", display_item.get_display_layer_property(0, "label"))
            # try the redo
            document_controller.handle_redo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(2, len(display_item.data_items))
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual("A", display_item.get_display_layer_property(0, "label"))
            self.assertEqual(new_fill_color, display_item.get_display_layer_property(1, "fill_color"))

    def test_setting_display_panel_data_item_to_none_clears_the_display(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_item(display_item)
            self.assertEqual(display_item, display_panel.display_item)
            self.assertEqual(data_item, display_panel.data_item)
            display_panel.set_display_item(None)
            self.assertEqual(None, display_panel.display_item)
            self.assertEqual(None, display_panel.data_item)

    def test_setting_display_panel_data_item_reference_updates_when_data_item_set_before_added_to_library(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            data_item_reference = DocumentModel.DocumentModel.DataItemReference(document_model, "abc", document_model._project)
            with contextlib.closing(data_item_reference):
                data_item_reference.data_item = data_item
                display_panel = document_controller.selected_display_panel
                display_panel.set_data_item_reference(data_item_reference)
                self.assertEqual(None, display_panel.display_item)
                self.assertEqual(None, display_panel.data_item)
                document_model.append_data_item(data_item)
                document_controller.periodic()
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual(display_item, display_panel.display_item)
                self.assertEqual(data_item, display_panel.data_item)

    def test_move_display_layer_from_display_to_display_undo_redo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.ones(8, ))
            data_item2 = DataItem.DataItem(numpy.ones(8, ))
            data_item3 = DataItem.DataItem(numpy.ones(8, ))
            data_item4 = DataItem.DataItem(numpy.ones(8, ))
            data_item5 = DataItem.DataItem(numpy.ones(8, ))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            document_model.append_data_item(data_item4)
            document_model.append_data_item(data_item5)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2), display_layer=DisplayItem.DisplayLayer())
            display_item1.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item3), display_layer=DisplayItem.DisplayLayer())
            display_item4 = document_model.get_display_item_for_data_item(data_item4)
            display_item4.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item5), display_layer=DisplayItem.DisplayLayer())
            display_item4.set_display_property("legend_position", None)
            new_legend_position = display_item4.get_display_property("legend_position")
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(data_item2, display_item1.display_data_channels[1].data_item)
            self.assertEqual(2, len(display_item4.display_layers))
            self.assertEqual(2, len(display_item4.display_data_channels))
            self.assertEqual(new_legend_position, display_item4.get_display_property("legend_position"))
            command = DisplayPanel.MoveDisplayLayerCommand(document_model, display_item1, 1, display_item4, 1)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(2, len(display_item1.display_layers))
            self.assertEqual(2, len(display_item1.display_data_channels))
            self.assertEqual(3, len(display_item4.display_layers))
            self.assertEqual(3, len(display_item4.display_data_channels))
            self.assertEqual(data_item2, display_item4.display_data_channels[2].data_item)
            self.assertEqual(display_item4.display_data_channels[2], display_item4.get_display_layer_display_data_channel(1))
            command.undo()
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(data_item2, display_item1.display_data_channels[1].data_item)
            self.assertEqual(2, len(display_item4.display_layers))
            self.assertEqual(2, len(display_item4.display_data_channels))
            self.assertEqual(new_legend_position, display_item4.get_display_property("legend_position"))
            command.redo()
            self.assertEqual(2, len(display_item1.display_layers))
            self.assertEqual(2, len(display_item1.display_data_channels))
            self.assertEqual(3, len(display_item4.display_layers))
            self.assertEqual(3, len(display_item4.display_data_channels))
            self.assertEqual(data_item2, display_item4.display_data_channels[2].data_item)
            self.assertEqual(display_item4.display_data_channels[2], display_item4.get_display_layer_display_data_channel(1))

    def test_move_display_layer_within_display_undo_redo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.ones(8, ))
            data_item2 = DataItem.DataItem(numpy.ones(8, ))
            data_item3 = DataItem.DataItem(numpy.ones(8, ))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2), display_layer=DisplayItem.DisplayLayer())
            display_item1.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item3), display_layer=DisplayItem.DisplayLayer())
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[2], display_item1.get_display_layer_display_data_channel(2))
            command = DisplayPanel.MoveDisplayLayerCommand(document_model, display_item1, 2, display_item1, 1)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[2], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(2))
            command.undo()
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[2], display_item1.get_display_layer_display_data_channel(2))
            command.redo()
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[2], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(2))

    def test_move_display_layer_backward_within_display_undo_redo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.ones(8, ))
            data_item2 = DataItem.DataItem(numpy.ones(8, ))
            data_item3 = DataItem.DataItem(numpy.ones(8, ))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2), display_layer=DisplayItem.DisplayLayer())
            display_item1.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item3), display_layer=DisplayItem.DisplayLayer())
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[2], display_item1.get_display_layer_display_data_channel(2))
            command = DisplayPanel.MoveDisplayLayerCommand(document_model, display_item1, 1, display_item1, 2)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[2], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(2))
            command.undo()
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[2], display_item1.get_display_layer_display_data_channel(2))
            command.redo()
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(3, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[2], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(2))

    def test_move_display_layer_with_multi_use_display_data_channel_to_another_display_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8,)))
            data_item2 = DataItem.DataItem(numpy.zeros((8,)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            # add a new layer
            display_item.add_display_layer_for_display_data_channel(display_item.display_data_channels[0])
            # confirm
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(display_item2.display_layers))
            self.assertEqual(1, len(display_item2.display_data_channels))
            # move the 2nd display layer to other display item
            command = DisplayPanel.MoveDisplayLayerCommand(document_controller.document_model, display_item, 1, display_item2, 1)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(2, len(display_item2.display_layers))
            self.assertEqual(2, len(display_item2.display_data_channels))
            command.undo()
            # tricky because display data channel was created on new display item and needs to be undone properly
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(display_item2.display_layers))
            self.assertEqual(1, len(display_item2.display_data_channels))
            command.redo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(1, len(display_item.display_layers))
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(2, len(display_item2.display_layers))
            self.assertEqual(2, len(display_item2.display_data_channels))

    def test_move_display_layer_with_same_display_data_channel(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # add a new layer
            display_item.add_display_layer_for_display_data_channel(display_item.display_data_channels[0])
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            # move the 2nd display layer forward
            command = DisplayPanel.MoveDisplayLayerCommand(document_controller.document_model, display_item, 1, display_item, 0)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            command.undo()
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))
            command.redo()
            self.assertEqual(2, len(display_item.display_layers))
            self.assertEqual(1, len(display_item.display_data_channels))
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(1, len(document_model.display_items))

    def test_add_display_layer_undo_redo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.ones(8, ))
            data_item2 = DataItem.DataItem(numpy.ones(8, ))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2), display_layer=DisplayItem.DisplayLayer())
            self.assertEqual(2, len(display_item1.display_layers))
            self.assertEqual(2, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(1))
            command = DisplayPanel.AddDisplayLayerCommand(document_model, display_item1, 1)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(2, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(2))
            command.undo()
            self.assertEqual(2, len(display_item1.display_layers))
            self.assertEqual(2, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(1))
            command.redo()
            self.assertEqual(3, len(display_item1.display_layers))
            self.assertEqual(2, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(1))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(2))

    def test_remove_display_layer_undo_redo(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.ones(8, ))
            data_item2 = DataItem.DataItem(numpy.ones(8, ))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.append_display_data_channel(DisplayItem.DisplayDataChannel(data_item=data_item2), display_layer=DisplayItem.DisplayLayer())
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_item(display_item1)
            self.assertEqual(2, len(display_item1.display_layers))
            self.assertEqual(2, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(1))
            command = DisplayPanel.RemoveDisplayLayerCommand(document_model, display_item1, 1)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(1, len(display_item1.display_layers))
            self.assertEqual(1, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            command.undo()
            self.assertEqual(2, len(display_item1.display_layers))
            self.assertEqual(2, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))
            self.assertEqual(display_item1.display_data_channels[1], display_item1.get_display_layer_display_data_channel(1))
            command.redo()
            self.assertEqual(1, len(display_item1.display_layers))
            self.assertEqual(1, len(display_item1.display_data_channels))
            self.assertEqual(display_item1.display_data_channels[0], display_item1.get_display_layer_display_data_channel(0))

    def test_selection_updated_when_filter_is_updated(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            display_panel = document_controller.selected_display_panel
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones(8, ))
            document_model.append_data_item(data_item)
            display_panel.set_displayed_data_item(data_item)
            data_item1 = document_controller.processing_invert().data_item
            display_panel.set_displayed_data_item(data_item1)
            document_controller.processing_invert()
            display_panel.set_displayed_data_item(data_item1)
            document_controller.periodic()
            document_controller.display_filter = ListModel.TextFilter("text_for_filter", "99")
            data_item.set_data(numpy.zeros(8, ))
            document_controller.periodic()

    def test_filter_masks_can_be_created_on_a_variety_of_displays(self):
        filter_mask_fns = [
            ("create_spot", [Geometry.FloatPoint(x=20, y=20)]),
            ("create_wedge", [1.0]),
            ("create_ring", [20.0]),
            ("create_lattice", [Geometry.FloatPoint(x=20, y=20)]),
        ]
        data_and_metadata_list = [
            DataAndMetadata.new_data_and_metadata(numpy.ones((100, 100)), data_descriptor=DataAndMetadata.DataDescriptor(False, 0, 2)),
            DataAndMetadata.new_data_and_metadata(numpy.ones((100, 100, 2)), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 1)),
            DataAndMetadata.new_data_and_metadata(numpy.ones((100, 100, 2, 2)), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2)),
        ]
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            for data_and_metadata in data_and_metadata_list:
                data_item = DataItem.new_data_item(data_and_metadata)
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_panel = document_controller.selected_display_panel
                display_panel.set_displayed_data_item(data_item)
                for filter_mask_fn_name, filter_mask_fn_params in filter_mask_fns:
                    graphic = getattr(display_panel, filter_mask_fn_name)(*filter_mask_fn_params)
                    display_item.remove_graphic(graphic).close()
                document_model.remove_data_item(data_item)

    def test_dropping_datum_1d_on_existing_line_plot_works(self):
        with TestContext.create_memory_context() as test_context:
            # set up the layout
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.workspace_controller.display_panels[0]
            data_item = DataItem.DataItem(numpy.zeros((12,)))
            data_item2 = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.zeros((10,10)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 1)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=200, width=100))
            mime_data = document_controller.ui.create_mime_data()
            MimeTypes.mime_data_put_display_item(mime_data, display_item2)
            display_panel.content_canvas_item._set_drop_region(list(display_panel.display_canvas_item.get_drop_regions_map(display_item2).keys())[0])
            display_panel.content_canvas_item.drop(mime_data, 100, 50)
            new_display_item = document_model.display_items[-1]
            self.assertEqual(2, len(new_display_item.display_data_channels))

    def test_cursor_task_is_closed_when_display_panel_is_emptied(self):
        with TestContext.create_memory_context() as test_context:
            # set up the layout
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.workspace_controller.display_panels[0]
            data_item = DataItem.DataItem(numpy.zeros((12,12)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=200, width=200))
            display_panel.cursor_changed((100, 100))
            document_model.remove_data_item(data_item)
            document_controller.periodic()

    def test_making_composite_display_items(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.new_data_item(numpy.zeros(8,)))
            document_model.append_data_item(DataItem.new_data_item(numpy.zeros(8,)))
            document_model.append_data_item(DataItem.new_data_item(numpy.zeros(8,)))
            data_item1, data_item2, data_item3 = document_model.data_items
            display_item1, display_item2, display_item3 = document_model.display_items
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item1)
            # check assumptions
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(3, len(document_model.display_items))
            # add item 2 to item 1
            document_controller.add_display_data_channel_to_or_create_composite(display_item1, display_item2, display_panel)
            # check that a new data item was created that contains item 1 and item 2
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(4, len(document_model.display_items))
            new_display_item = document_model.display_items[-1]
            self.assertEqual(2, len(new_display_item.display_layers))
            self.assertEqual(2, len(new_display_item.display_data_channels))
            self.assertEqual(data_item1, new_display_item.data_items[0])
            self.assertEqual(data_item2, new_display_item.data_items[1])
            # undo and check original assumptions
            document_controller.last_undo_command.undo()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(3, len(document_model.display_items))
            # redo and recheck new data item
            document_controller.last_undo_command.redo()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(4, len(document_model.display_items))
            new_display_item = document_model.display_items[-1]
            self.assertEqual(2, len(new_display_item.display_layers))
            self.assertEqual(2, len(new_display_item.display_data_channels))
            self.assertEqual(data_item1, new_display_item.data_items[0])
            self.assertEqual(data_item2, new_display_item.data_items[1])
            # add item 3 to the new composite item and check that there are three layers
            document_controller.add_display_data_channel_to_or_create_composite(new_display_item, display_item3, display_panel)
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(4, len(document_model.display_items))
            new_display_item = document_model.display_items[-1]
            self.assertEqual(3, len(new_display_item.display_layers))
            self.assertEqual(3, len(new_display_item.display_data_channels))
            self.assertEqual(data_item1, new_display_item.data_items[0])
            self.assertEqual(data_item2, new_display_item.data_items[1])
            self.assertEqual(data_item3, new_display_item.data_items[2])
            # undo check assumptions
            document_controller.last_undo_command.undo()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(4, len(document_model.display_items))
            new_display_item = document_model.display_items[-1]
            self.assertEqual(2, len(new_display_item.display_layers))
            self.assertEqual(2, len(new_display_item.display_data_channels))
            self.assertEqual(data_item1, new_display_item.data_items[0])
            self.assertEqual(data_item2, new_display_item.data_items[1])
            # redo and check
            document_controller.last_undo_command.redo()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(4, len(document_model.display_items))
            new_display_item = document_model.display_items[-1]
            self.assertEqual(3, len(new_display_item.display_layers))
            self.assertEqual(3, len(new_display_item.display_data_channels))
            self.assertEqual(data_item1, new_display_item.data_items[0])
            self.assertEqual(data_item2, new_display_item.data_items[1])
            self.assertEqual(data_item3, new_display_item.data_items[2])

    def test_making_composite_display_items_keeps_colors(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.new_data_item(numpy.zeros(8,)))
            document_model.append_data_item(DataItem.new_data_item(numpy.zeros(8,)))
            document_model.append_data_item(DataItem.new_data_item(numpy.zeros(8,)))
            display_item1, display_item2, display_item3 = document_model.display_items
            display_item1.display_layers[0].fill_color = "red"
            display_item1.display_layers[0].stroke_color = "red"
            display_item2.display_layers[0].fill_color = "green"
            display_item2.display_layers[0].stroke_color = None
            display_item3.display_layers[0].fill_color = None
            display_item3.display_layers[0].stroke_color = "blue"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item1)
            document_controller.add_display_data_channel_to_or_create_composite(display_item1, display_item2, display_panel)
            new_display_item = document_model.display_items[-1]
            document_controller.add_display_data_channel_to_or_create_composite(new_display_item, display_item3, display_panel)
            self.assertEqual("red", new_display_item.display_layers[0].fill_color)
            self.assertEqual("red", new_display_item.display_layers[0].stroke_color)
            self.assertIsNone(new_display_item.display_layers[1].fill_color)
            self.assertEqual("green", new_display_item.display_layers[1].stroke_color)
            self.assertIsNone(new_display_item.display_layers[2].fill_color)
            self.assertEqual("blue", new_display_item.display_layers[2].stroke_color)

    def test_interval_zoom(self):
        intervals = [(-2.5, -1.5), (-1.5, 0.0), (-1.5, 0.5), (0.0, 1.0), (0.5, 0.5), (0.5, 1.5), (1, 2.5), (2.5, 3.5)]
        # Fails on (1.0, 0)

        for interval in intervals:
            with TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller()
                document_model = document_controller.document_model
                data_item = DataItem.DataItem(create_1d_data(length=1024, data_min=0, data_max=1))
                document_model.append_data_item(data_item)
                display_panel = document_controller.selected_display_panel
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_panel.set_display_panel_display_item(display_item)
                canvas_shape = (480, 640)
                document_controller.show_display_item(display_item)
                display_panel.display_canvas_item.layout_immediate(canvas_shape)
                display_panel.display_canvas_item.refresh_layout_immediate()
                line_plot_canvas_item = typing.cast(LinePlotCanvasItem.LinePlotCanvasItem, display_panel.display_canvas_item)
                interval_graphic = Graphics.IntervalGraphic()
                # ensure the interval is outside the regular fractional coordinate range
                interval_graphic.start = interval[0]
                interval_graphic.end = interval[1]
                padding = abs(interval[1] - interval[0]) * 0.5
                document_model.get_display_item_for_data_item(data_item).add_graphic(interval_graphic)
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_item.graphic_selection.set(0)
                line_plot_canvas_item.handle_auto_display()
                axes = line_plot_canvas_item._axes
                self.assertAlmostEqual(axes.drawn_left_channel, (min(interval) - padding) * 1024)
                self.assertAlmostEqual(axes.drawn_right_channel, (max(interval) + padding) * 1024)

    def test_composite_line_plot_interval_zoom_with_different_intensity_calibration_scales(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data1 = numpy.array([x for x in range(-5, 7)]) * 1
            data_item1 = DataItem.DataItem(data1)
            data_item1.set_xdata(DataAndMetadata.new_data_and_metadata(data1, Calibration.Calibration(0, 1, "z")))
            data2 = numpy.array([x for x in range(-5, 7)]) * 2
            data_item2 = DataItem.DataItem(data2)
            data_item2.set_xdata(DataAndMetadata.new_data_and_metadata(data2, Calibration.Calibration(0, 8, "z")))

            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_panel = document_controller.selected_display_panel
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.display_type = "line_plot"
            display_panel.set_display_panel_display_item(display_item)
            document_controller.add_display_data_channel_to_composite(display_item, document_model.get_display_item_for_data_item(data_item2))
            display_panel.update()
            canvas_shape = (480, 640)
            document_controller.show_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(canvas_shape)
            display_panel.display_canvas_item.refresh_layout_immediate()
            line_plot_canvas_item = typing.cast(LinePlotCanvasItem.LinePlotCanvasItem, display_panel.display_canvas_item)

            interval_graphic = Graphics.IntervalGraphic()
            # ensure the interval is outside the regular fractional coordinate range
            interval_graphic.start = 0.25
            interval_graphic.end = 0.75
            display_item.add_graphic(interval_graphic)
            display_item.graphic_selection.set(0)
            line_plot_canvas_item.handle_auto_display()
            axes = line_plot_canvas_item._axes
            self.assertAlmostEqual(axes.drawn_left_channel, 0)
            self.assertAlmostEqual(axes.drawn_right_channel, 12)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(48.0) * 1.2, axes.uncalibrated_data_max)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(-32.0) * 1.2, axes.uncalibrated_data_min)

    def test_composite_line_plot_interval_zoom_with_different_intensity_calibrations_with_no_selected_interval(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data1 = numpy.array([x for x in range(-5, 7)]) * 1
            data_item1 = DataItem.DataItem(data1)
            data_item1.set_xdata(DataAndMetadata.new_data_and_metadata(data1, Calibration.Calibration(0, 1, "z")))
            data2 = numpy.array([x for x in range(-5, 7)]) * 2
            data_item2 = DataItem.DataItem(data2)
            data_item2.set_xdata(DataAndMetadata.new_data_and_metadata(data2, Calibration.Calibration(0, 8, "z")))

            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_panel = document_controller.selected_display_panel
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.display_type = "line_plot"
            display_panel.set_display_panel_display_item(display_item)
            document_controller.add_display_data_channel_to_composite(display_item, document_model.get_display_item_for_data_item(data_item2))
            display_panel.update()
            canvas_shape = (480, 640)
            document_controller.show_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(canvas_shape)
            display_panel.display_canvas_item.refresh_layout_immediate()
            line_plot_canvas_item = typing.cast(LinePlotCanvasItem.LinePlotCanvasItem, display_panel.display_canvas_item)

            line_plot_canvas_item.handle_auto_display()
            axes = line_plot_canvas_item._axes
            self.assertAlmostEqual(axes.drawn_left_channel, 0.0)  # no interval selected, so no padding
            self.assertAlmostEqual(axes.drawn_right_channel, 12.0)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(96.0) * 1.2, axes.uncalibrated_data_max)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(-80.0) * 1.2, axes.uncalibrated_data_min)

    def test_composite_line_plot_interval_zoom_with_different_intensity_calibrations_with_different_intensity_units(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data1 = numpy.array([x for x in range(-5, 7)]) * 1
            data_item1 = DataItem.DataItem(data1)
            data_item1.set_xdata(DataAndMetadata.new_data_and_metadata(data1, Calibration.Calibration(0, 1, "z")))
            data2 = numpy.array([x for x in range(-5, 7)]) * 2
            data_item2 = DataItem.DataItem(data2)
            data_item2.set_xdata(DataAndMetadata.new_data_and_metadata(data2, Calibration.Calibration(0, 8, "x")))

            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_panel = document_controller.selected_display_panel
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.display_type = "line_plot"
            display_panel.set_display_panel_display_item(display_item)
            document_controller.add_display_data_channel_to_composite(display_item, document_model.get_display_item_for_data_item(data_item2))
            display_panel.update()
            canvas_shape = (480, 640)
            document_controller.show_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(canvas_shape)
            display_panel.display_canvas_item.refresh_layout_immediate()
            line_plot_canvas_item = typing.cast(LinePlotCanvasItem.LinePlotCanvasItem, display_panel.display_canvas_item)

            interval_graphic = Graphics.IntervalGraphic()
            # ensure the interval is outside the regular fractional coordinate range
            interval_graphic.start = 0.25
            interval_graphic.end = 0.75
            display_item.add_graphic(interval_graphic)
            display_item.graphic_selection.set(0)
            line_plot_canvas_item.handle_auto_display()
            axes = line_plot_canvas_item._axes
            self.assertAlmostEqual(axes.drawn_left_channel, 0)
            self.assertAlmostEqual(axes.drawn_right_channel, 12)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(3.0) * 1.2, axes.uncalibrated_data_max)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(-2.0) * 1.2, axes.uncalibrated_data_min)

    def test_composite_line_plot_interval_zoom_with_different_intensity_calibrations_with_intensity_offset(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data1 = numpy.array([x for x in range(-5, 7)]) * 1
            data_item1 = DataItem.DataItem(data1)
            data_item1.set_xdata(DataAndMetadata.new_data_and_metadata(data1, Calibration.Calibration(-5, 1, "z")))
            data2 = numpy.array([x for x in range(-5, 7)]) * 1
            data_item2 = DataItem.DataItem(data2)
            data_item2.set_xdata(DataAndMetadata.new_data_and_metadata(data2, Calibration.Calibration(4, 2, "z")))

            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_panel = document_controller.selected_display_panel
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.display_type = "line_plot"
            display_panel.set_display_panel_display_item(display_item)
            document_controller.add_display_data_channel_to_composite(display_item, document_model.get_display_item_for_data_item(data_item2))
            display_panel.update()
            canvas_shape = (480, 640)
            document_controller.show_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(canvas_shape)
            display_panel.display_canvas_item.refresh_layout_immediate()
            line_plot_canvas_item = typing.cast(LinePlotCanvasItem.LinePlotCanvasItem, display_panel.display_canvas_item)

            interval_graphic = Graphics.IntervalGraphic()
            # ensure the interval is outside the regular fractional coordinate range
            interval_graphic.start = 0.25
            interval_graphic.end = 0.75
            display_item.add_graphic(interval_graphic)
            display_item.graphic_selection.set(0)
            line_plot_canvas_item.handle_auto_display()
            axes = line_plot_canvas_item._axes
            self.assertAlmostEqual(axes.drawn_left_channel, 0)
            self.assertAlmostEqual(axes.drawn_right_channel, 12)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(10.0) * 1.2, axes.uncalibrated_data_max)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(-7.0) * 1.2, axes.uncalibrated_data_min)

    def test_composite_line_plot_interval_zoom_with_different_intensity_calibrations_with_multiple_intervals(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data1 = numpy.array([x for x in range(20)]) * 1
            data_item1 = DataItem.DataItem(data1)
            data_item1.set_xdata(DataAndMetadata.new_data_and_metadata(data1, Calibration.Calibration(0, 1, "z")))
            data2 = numpy.array([x for x in range(20)]) * 2
            data_item2 = DataItem.DataItem(data2)
            data_item2.set_xdata(DataAndMetadata.new_data_and_metadata(data2, Calibration.Calibration(0, 1, "z")))

            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_panel = document_controller.selected_display_panel
            display_item = document_model.get_display_item_for_data_item(data_item1)
            display_item.display_type = "line_plot"
            display_panel.set_display_panel_display_item(display_item)
            document_controller.add_display_data_channel_to_composite(display_item, document_model.get_display_item_for_data_item(data_item2))
            display_panel.update()
            canvas_shape = (480, 640)
            document_controller.show_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(canvas_shape)
            display_panel.display_canvas_item.refresh_layout_immediate()
            line_plot_canvas_item = typing.cast(LinePlotCanvasItem.LinePlotCanvasItem, display_panel.display_canvas_item)

            interval_pairs = [(.25, .33), (.35, .45), (.55, .66)]
            index = 0
            for interval in interval_pairs:
                index += 1
                interval_graphic = Graphics.IntervalGraphic()
                interval_graphic.start = interval[0]
                interval_graphic.end = interval[1]
                display_item.add_graphic(interval_graphic)
                display_item.graphic_selection.add(display_item.graphics.index(interval_graphic))
            line_plot_canvas_item.handle_auto_display()
            axes = line_plot_canvas_item._axes
            self.assertAlmostEqual(axes.drawn_left_channel, 1)
            self.assertAlmostEqual(axes.drawn_right_channel, 17)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(26.0) * 1.2, axes.uncalibrated_data_max)
            self.assertAlmostEqual(data_item1.intensity_calibration.convert_from_calibrated_value(0.0) * 1.2, axes.uncalibrated_data_min)

    def test_display_tracker_updates_when_inherited_title_updates(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8,)))
            data_item.title = "red"
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
            data_item2.title = None
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            document_model.recompute_all()
            self.assertEqual("red", display_item.displayed_title)
            self.assertEqual("red (Negate)", display_item2.displayed_title)
            display_panel = document_controller.selected_display_panel
            display_tracker = DisplayPanel.DisplayTracker(display_item2, DisplayPanel.DisplayPanelUISettings(document_controller.ui), display_panel, document_controller.event_loop, False)
            with contextlib.closing(display_tracker):
                title_changed = False
                def handle_title_changed(title: str) -> None:
                    nonlocal title_changed
                    title_changed = True
                display_tracker.on_title_changed = handle_title_changed
                data_item.title = "green"
                self.assertTrue(title_changed)

    def test_index_sliders_update_when_data_created_later(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((8, 8)), data_descriptor=DataAndMetadata.DataDescriptor(False, 0, 2)))
            document_controller.periodic()
            sequence_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-3].canvas_items[1]
            c0_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-2].canvas_items[1]
            c1_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-1].canvas_items[1]
            self.assertEqual(0, len(sequence_slider_row.canvas_items))
            self.assertEqual(0, len(c0_slider_row.canvas_items))
            self.assertEqual(0, len(c1_slider_row.canvas_items))
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((8, 8, 8)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2)))
            document_controller.periodic()
            self.assertNotEqual(0, len(sequence_slider_row.canvas_items))
            self.assertEqual(0, len(c0_slider_row.canvas_items))
            self.assertEqual(0, len(c1_slider_row.canvas_items))

    def test_index_sliders_update_when_data_changed(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
            sequence_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-3].canvas_items[1]
            c0_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-2].canvas_items[1]
            c1_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-1].canvas_items[1]
            self.assertEqual(0, len(sequence_slider_row.canvas_items))
            self.assertEqual(0, len(c0_slider_row.canvas_items))
            self.assertEqual(0, len(c1_slider_row.canvas_items))
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((8, 8, 8)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2)))
            document_controller.periodic()
            self.assertNotEqual(0, len(sequence_slider_row.canvas_items))
            self.assertEqual(0, len(c0_slider_row.canvas_items))
            self.assertEqual(0, len(c1_slider_row.canvas_items))
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((4, 4, 4, 4)), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2)))
            document_controller.periodic()
            self.assertEqual(0, len(sequence_slider_row.canvas_items))
            self.assertNotEqual(0, len(c0_slider_row.canvas_items))
            self.assertNotEqual(0, len(c1_slider_row.canvas_items))
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((2, 4, 4, 4, 4)), data_descriptor=DataAndMetadata.DataDescriptor(True, 2, 2)))
            document_controller.periodic()
            self.assertNotEqual(0, len(sequence_slider_row.canvas_items))
            self.assertNotEqual(0, len(c0_slider_row.canvas_items))
            self.assertNotEqual(0, len(c1_slider_row.canvas_items))
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((8, 8)), data_descriptor=DataAndMetadata.DataDescriptor(False, 0, 2)))
            document_controller.periodic()
            self.assertEqual(0, len(sequence_slider_row.canvas_items))
            self.assertEqual(0, len(c0_slider_row.canvas_items))
            self.assertEqual(0, len(c1_slider_row.canvas_items))

    def test_index_sliders_update_when_indexes_changed(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
            sequence_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-3].canvas_items[1]
            c0_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-2].canvas_items[1]
            c1_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-1].canvas_items[1]
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((2, 4, 4, 4, 4)), data_descriptor=DataAndMetadata.DataDescriptor(True, 2, 2)))
            document_controller.periodic()
            self.assertEqual(0.0, sequence_slider_row.canvas_items[3].value)
            self.assertEqual(0.0, c0_slider_row.canvas_items[1].value)
            self.assertEqual(0.0, c1_slider_row.canvas_items[1].value)
            display_item.display_data_channel.sequence_index = 1
            self.assertEqual(1.0, sequence_slider_row.canvas_items[3].value)
            self.assertEqual(0.0, c0_slider_row.canvas_items[1].value)
            self.assertEqual(0.0, c1_slider_row.canvas_items[1].value)
            display_item.display_data_channel.collection_index = (2, 3)
            self.assertEqual(1.0, sequence_slider_row.canvas_items[3].value)
            self.assertAlmostEqual(2.0/3.0, c0_slider_row.canvas_items[1].value)
            self.assertEqual(1.0, c1_slider_row.canvas_items[1].value)

    def test_index_sliders_update_when_data_created_with_display(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((1, 8, 8)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2)))
            document_controller.periodic()
            sequence_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-3].canvas_items[1]
            c0_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-2].canvas_items[1]
            c1_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-1].canvas_items[1]
            self.assertNotEqual(0, len(sequence_slider_row.canvas_items))
            self.assertEqual(0, len(c0_slider_row.canvas_items))
            self.assertEqual(0, len(c1_slider_row.canvas_items))

    def test_index_sequence_slider_works_after_dropping_onto_empty_display_panel(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem()
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((8, 8, 8)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_data_channel.sequence_index = 1
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
            sequence_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-3].canvas_items[1]
            self.assertNotEqual(0, len(sequence_slider_row.canvas_items))
            self.assertAlmostEqual(1.0/7.0, sequence_slider_row.canvas_items[3].value)
            sequence_slider_row.canvas_items[3].value_change_stream.begin()
            sequence_slider_row.canvas_items[3].value = 2.0/7.0
            sequence_slider_row.canvas_items[3].value_change_stream.end()
            document_controller.periodic()
            self.assertEqual(2, display_item.display_data_channel.sequence_index)

    def test_index_sequence_slider_works_after_dropping_onto_existing_display_panel(self):
        with TestContext.create_memory_context() as test_context:
            # this tests handling of invalid intermediate combined tuples in slider apparatus
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # drop a basic image
            data_item = DataItem.DataItem(numpy.zeros((4,4)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
            # drop a sequence
            data_item = DataItem.DataItem()
            data_item.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(numpy.zeros((8, 8, 8)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_data_channel.sequence_index = 1
            display_panel.set_display_panel_display_item(display_item)
            document_controller.periodic()
            sequence_slider_row = display_panel.display_canvas_item.canvas_items[2].canvas_items[-3].canvas_items[1]
            self.assertNotEqual(0, len(sequence_slider_row.canvas_items))
            self.assertAlmostEqual(1.0/7.0, sequence_slider_row.canvas_items[3].value)
            sequence_slider_row.canvas_items[3].value_change_stream.begin()
            sequence_slider_row.canvas_items[3].value = 2.0/7.0
            sequence_slider_row.canvas_items[3].value_change_stream.end()
            document_controller.periodic()
            self.assertEqual(2, display_item.display_data_channel.sequence_index)

    def test_hand_tool_undo(self):
        # testing during the development of the mouse handler and the undo/redo system with actions
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            display_panel.perform_action("set_fit_mode")
            self.assertEqual((0.5, 0.5), tuple(display_item.display_properties["image_position"]))
            document_controller.tool_mode = "hand"
            display_panel.display_canvas_item.simulate_drag((100,100), (200,200))
            document_controller.periodic()
            self.assertEqual((0.4, 0.4), tuple(display_item.display_properties["image_position"]))
            # undo check assumptions
            document_controller.handle_undo()
            self.assertEqual((0.5, 0.5), tuple(display_item.display_properties["image_position"]))
            # redo check assumptions
            document_controller.handle_redo()
            self.assertEqual((0.4, 0.4), tuple(display_item.display_properties["image_position"]))
            # move again
            display_panel.display_canvas_item.simulate_drag((100,100), (200,200))
            document_controller.periodic()
            self.assertEqual((0.3, 0.3), tuple(display_item.display_properties["image_position"]))
            # undo check assumptions
            document_controller.handle_undo()
            self.assertEqual((0.4, 0.4), tuple(display_item.display_properties["image_position"]))
            # undo again check assumptions
            document_controller.handle_undo()
            self.assertEqual((0.5, 0.5), tuple(display_item.display_properties["image_position"]))

    def test_raster_display_handles_invalid_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.zeros((8,8)), dimensional_calibrations=[Calibration.Calibration(0.0, -math.inf, "x"), Calibration.Calibration(0.0, -math.inf, "x")]))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            DisplayPanel.preview(DisplayPanel.DisplayPanelUISettings(document_controller.ui), display_item, 512, 512)

    def test_line_plot_display_handles_invalid_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.zeros((8,)), dimensional_calibrations=[Calibration.Calibration(0.0, -math.inf, "x")]))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            DisplayPanel.preview(DisplayPanel.DisplayPanelUISettings(document_controller.ui), display_item, 512, 128)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
