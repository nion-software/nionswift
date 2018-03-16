# standard libraries
import contextlib
import logging
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import DisplayPanel
from nion.swift import Facade
from nion.swift import ImageCanvasItem
from nion.swift import LinePlotCanvasItem
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import TestUI
from nion.utils import Geometry


Facade.initialize()


class TestGraphicSelectionClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_selection_set(self):
        selection = Display.GraphicSelection()
        selection.set(0)
        selection.set(1)
        self.assertEqual(len(selection.indexes), 1)


def create_1d_data(length=1024, data_min=0.0, data_max=1.0):
    data = numpy.zeros((length, ), dtype=numpy.float64)
    irow = numpy.ogrid[0:length]
    data[:] = data_min + (data_max - data_min) * (irow / float(length))
    return data


class TestDisplayPanel:
    def __init__(self):
        self.drop_region = None
    def handle_drag_enter(self, mime_data):
        return "copy"
    def handle_drag_move(self, mime_data, x, y):
        return "copy"
    def handle_drop(self, mime_data, region, x, y):
        self.drop_region = region
        return "copy"


class TestDisplayPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)
        self.document_model = DocumentModel.DocumentModel()
        self.document_controller = DocumentController.DocumentController(self.app.ui, self.document_model, workspace_id="library")
        self.display_panel = self.document_controller.selected_display_panel
        self.data_item = DataItem.DataItem(numpy.zeros((10, 10)))
        self.document_model.append_data_item(self.data_item)
        self.display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        self.display_panel.set_display_panel_data_item(self.data_item)
        header_height = self.display_panel.header_canvas_item.header_height
        self.display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))

    def tearDown(self):
        self.document_controller.close()

    def setup_line_plot(self, canvas_shape=None, data_min=0.0, data_max=1.0):
        canvas_shape = canvas_shape if canvas_shape else (480, 640)  # yes I know these are backwards
        data_item_1d = DataItem.DataItem(create_1d_data(data_min=data_min, data_max=data_max))
        self.document_model.append_data_item(data_item_1d)
        self.display_panel.set_display_panel_data_item(data_item_1d)
        self.display_panel.display_canvas_item.layout_immediate(canvas_shape)
        self.display_panel_drawing_context = DrawingContext.DrawingContext()
        self.display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_1d)
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        self.display_panel.display_canvas_item.refresh_layout_immediate()
        return self.display_panel.display_canvas_item

    def setup_3d_data(self, canvas_shape=None):
        canvas_shape = canvas_shape if canvas_shape else (640, 480)  # yes I know these are backwards
        data_item_3d = DataItem.DataItem(numpy.ones((5, 5, 5)))
        self.document_model.append_data_item(data_item_3d)
        self.display_panel.set_display_panel_data_item(data_item_3d)
        self.display_panel.display_canvas_item.layout_immediate(canvas_shape)
        self.display_panel_drawing_context = DrawingContext.DrawingContext()
        self.display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_3d)
        # trigger layout
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        return self.display_panel.display_canvas_item

    def test_image_panel_gets_destructed(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = DisplayPanel.DisplayPanel(document_controller, dict())
            # add some extra refs for fun
            container = CanvasItem.SplitterCanvasItem()
            container.add_canvas_item(display_panel)
            canvas_widget = self.app.ui.create_canvas_widget()
            with contextlib.closing(canvas_widget):
                canvas_widget.canvas_item.add_canvas_item(container)
                # now take the weakref
                display_panel_weak_ref = weakref.ref(display_panel)
                display_panel = None
            self.assertIsNone(display_panel_weak_ref())

    # user deletes data item that is displayed. make sure we remove the display.
    def test_deleting_data_item_removes_it_from_image_panel(self):
        self.assertEqual(self.data_item, self.document_model.data_items[0])
        self.assertEqual(self.display_specifier.data_item, self.data_item)
        self.document_controller.processing_invert()
        self.document_controller.periodic()
        self.display_panel.set_display_panel_data_item(self.data_item)
        self.assertEqual(self.display_panel.data_item, self.data_item)
        self.document_model.remove_data_item(self.data_item)
        self.assertIsNone(self.display_panel.data_item)

    # user deletes data source of data item that is displayed. make sure to remove display if source is deleted.
    def test_deleting_data_item_with_processed_data_item_removes_processed_data_item_from_image_panel(self):
        self.assertEqual(self.display_panel.data_item, self.document_model.data_items[0])
        self.assertEqual(self.display_panel.data_item, self.data_item)
        inverted_data_item = self.document_controller.processing_invert().data_item
        self.document_controller.periodic()
        self.display_panel.set_display_panel_data_item(inverted_data_item)
        self.assertEqual(self.display_panel.data_item, inverted_data_item)
        self.document_model.remove_data_item(self.data_item)
        self.assertIsNone(self.display_panel.data_item)

    def test_select_line(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_graphic()
        # click outside so nothing is selected
        self.display_panel.display_canvas_item.simulate_click((0, 0))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 0)
        # select the line
        self.display_panel.display_canvas_item.simulate_click((200, 200))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_specifier.display.graphic_selection.indexes)
        # now shift the view and try again
        self.display_panel.display_canvas_item.simulate_click((0, 0))
        self.display_panel.display_canvas_item.move_left()  # 10 pixels left
        self.display_panel.display_canvas_item.move_left()  # 10 pixels left
        self.display_panel.display_canvas_item.simulate_click((200, 200))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 0)
        self.display_panel.display_canvas_item.simulate_click((220, 200))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_specifier.display.graphic_selection.indexes)

    def test_select_multiple(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_graphic()
        self.document_controller.add_ellipse_graphic()
        # click outside so nothing is selected
        self.display_panel.display_canvas_item.simulate_click((0, 0))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 0)
        # select the ellipse
        self.display_panel.display_canvas_item.simulate_click((725, 500))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(1 in self.display_specifier.display.graphic_selection.indexes)
        # select the line
        self.display_panel.display_canvas_item.simulate_click((200, 200))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_specifier.display.graphic_selection.indexes)
        # add the ellipse to the selection. click inside the right side.
        self.display_panel.display_canvas_item.simulate_click((725, 500), CanvasItem.KeyboardModifiers(control=True))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 2)
        self.assertTrue(0 in self.display_specifier.display.graphic_selection.indexes)
        # remove the ellipse from the selection. click inside the right side.
        self.display_panel.display_canvas_item.simulate_click((725, 500), CanvasItem.KeyboardModifiers(control=True))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_specifier.display.graphic_selection.indexes)

    def assertClosePoint(self, p1, p2, e=0.00001):
        self.assertTrue(Geometry.distance(p1, p2) < e)

    def assertCloseRectangle(self, r1, r2, e=0.00001):
        self.assertTrue(Geometry.distance(r1[0], r2[0]) < e and Geometry.distance(r1[1], r2[1]) < e)

    def test_drag_multiple(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_graphic()
        self.document_controller.add_ellipse_graphic()
        # make sure items are in the right place
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.display_specifier.display.graphics[1].bounds, ((0.25, 0.25), (0.5, 0.5)))
        # select both
        self.display_specifier.display.graphic_selection.set(0)
        self.display_specifier.display.graphic_selection.add(1)
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 2)
        # drag by (0.1, 0.2)
        self.display_panel.display_canvas_item.simulate_drag((500,500), (600,700))
        self.assertCloseRectangle(self.display_specifier.display.graphics[1].bounds, ((0.35, 0.45), (0.5, 0.5)))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.3, 0.4))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.9, 1.0))
        # drag on endpoint (0.3, 0.4) make sure it drags all
        self.display_panel.display_canvas_item.simulate_drag((300,400), (200,200))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.display_specifier.display.graphics[1].bounds, ((0.25, 0.25), (0.5, 0.5)))
        # now select just the line, drag middle of circle. should only drag circle.
        self.display_specifier.display.graphic_selection.set(0)
        self.display_panel.display_canvas_item.simulate_drag((700,500), (800,500))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.display_specifier.display.graphics[1].bounds, ((0.35, 0.25), (0.5, 0.5)))

    def test_drag_line_part(self):
        # add line (0.2, 0.2), (0.8, 0.8)
        self.document_controller.add_line_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.8, 0.8))
        # select it
        self.display_specifier.display.graphic_selection.set(0)
        self.display_panel.display_canvas_item.simulate_drag((200,200), (300,400))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.3, 0.4))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.8, 0.8))
        # shift drag a part, should not deselect and should align horizontally
        self.display_panel.display_canvas_item.simulate_drag((300,400), (350,700), CanvasItem.KeyboardModifiers(shift=True))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.35, 0.8))
        # shift drag start to top left quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((350,800), (370,340), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.34, 0.34))
        self.display_panel.display_canvas_item.simulate_drag((340,340), (240,270), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.24, 0.24))
        # shift drag start to bottom left quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((240,240), (370,1140), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.37, 1.23))
        self.display_panel.display_canvas_item.simulate_drag((370,1230), (370,1350), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.25, 1.35))
        # shift drag start to bottom right quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((250,1350), (1230,1175), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (1.23, 1.23))
        self.display_panel.display_canvas_item.simulate_drag((1230,1230), (1150,1210), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (1.21, 1.21))
        # shift drag start to top right quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((1210,1210), (1230,310), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (1.29, 0.31))
        self.display_panel.display_canvas_item.simulate_drag((1290,310), (1110,420), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (1.18, 0.42))
        # now reverse start/end and run the same test
        self.display_panel.display_canvas_item.simulate_drag((800,800), (200,200))
        self.display_panel.display_canvas_item.simulate_drag((1180,420), (800,800))
        # shift drag start to top left quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((200,200), (370,340), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.34, 0.34))
        self.display_panel.display_canvas_item.simulate_drag((340,340), (240,270), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.24, 0.24))
        # shift drag start to bottom left quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((240,240), (370,1140), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.37, 1.23))
        self.display_panel.display_canvas_item.simulate_drag((370,1230), (370,1350), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (0.25, 1.35))
        # shift drag start to bottom right quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((250,1350), (1230,1175), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (1.23, 1.23))
        self.display_panel.display_canvas_item.simulate_drag((1230,1230), (1150,1210), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (1.21, 1.21))
        # shift drag start to top right quadrant. check both y-maj and x-maj.
        self.display_panel.display_canvas_item.simulate_drag((1210,1210), (1230,310), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (1.29, 0.31))
        self.display_panel.display_canvas_item.simulate_drag((1290,310), (1110,420), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].end, (1.18, 0.42))

    def test_nudge_line(self):
        # add line (0.2, 0.2), (0.8, 0.8)
        self.document_controller.add_line_graphic()
        # select it
        self.display_specifier.display.graphic_selection.set(0)
        # move it left
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.200, 0.199))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.200, 0.189))
        # move it up
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.199, 0.189))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.189, 0.189))
        # move it right
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.189, 0.190))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.189, 0.200))
        # move it down
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.190, 0.200))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].start, (0.200, 0.200))

    def test_nudge_rect(self):
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_rectangle_graphic()
        # select it
        self.display_specifier.display.graphic_selection.set(0)
        # move it left
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.250, 0.249))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.250, 0.239))
        # move it up
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.249, 0.239))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.239, 0.239))
        # move it right
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.239, 0.240))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.239, 0.250))
        # move it down
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.240, 0.250))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.250, 0.250))

    def test_nudge_ellipse(self):
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_ellipse_graphic()
        # select it
        self.display_specifier.display.graphic_selection.set(0)
        # move it left
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.250, 0.249))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.250, 0.239))
        # move it up
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.249, 0.239))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.239, 0.239))
        # move it right
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.239, 0.240))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.239, 0.250))
        # move it down
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down"))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.240, 0.250))
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.250, 0.250))

    def test_drag_point_moves_the_point_graphic(self):
        # add point (0.5, 0.5)
        self.document_controller.add_point_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_specifier.display.graphics[0].position, (0.5, 0.5))
        # select it
        self.display_specifier.display.graphic_selection.set(0)
        self.display_panel.display_canvas_item.simulate_drag((500,500), (300,400))
        self.assertClosePoint(self.display_specifier.display.graphics[0].position, (0.3, 0.4))

    def test_click_on_point_selects_it(self):
        # add point (0.5, 0.5)
        self.document_controller.add_point_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_specifier.display.graphics[0].position, (0.5, 0.5))
        # select it
        self.display_panel.display_canvas_item.simulate_click((100,100))
        self.assertFalse(self.display_specifier.display.graphic_selection.indexes)
        self.display_panel.display_canvas_item.simulate_click((500,500))
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_specifier.display.graphic_selection.indexes)

    # this helps test out cursor positioning
    def test_map_widget_to_image(self):
        # assumes the test widget is 640x480
        self.display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
        self.assertIsNotNone(self.display_panel.display_canvas_item.map_widget_to_image((240, 320)))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image((240, 320)), (5, 5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image((0, 80)), (0.0, 0.0))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image((480, 560)), (10, 10))

    # this helps test out cursor positioning
    def test_map_widget_to_offset_image(self):
        # assumes the test widget is 640x480
        self.display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=480, width=640))
        self.display_panel.display_canvas_item.move_left()  # 10 pixels left
        self.display_panel.display_canvas_item.move_left()  # 10 pixels left
        self.assertIsNotNone(self.display_panel.display_canvas_item.map_widget_to_image((240, 320)))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image((240, 300)), (5, 5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image((0, 60)), (0.0, 0.0))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_widget_to_image((480, 540)), (10, 10))

    def test_resize_rectangle(self):
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_rectangle_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[1], (0.5, 0.5))
        # select it
        self.display_specifier.display.graphic_selection.set(0)
        # drag top left corner
        self.display_panel.display_canvas_item.simulate_drag((250,250), (300,250))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.30, 0.25))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[1], (0.45, 0.5))
        # drag with shift key
        self.display_panel.display_canvas_item.simulate_drag((300,250), (350,250), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[1], (0.5, 0.5))

    def test_resize_nonsquare_rectangle(self):
        self.data_item = DataItem.DataItem(numpy.zeros((20, 10)))
        self.document_model.append_data_item(self.data_item)
        self.display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        self.display_panel.set_display_panel_data_item(self.data_item)
        self.display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=2000, width=1000))
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_rectangle_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[1], (0.5, 0.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[0]), (5, 2.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[1]), (10, 5))
        # select it
        self.display_specifier.display.graphic_selection.set(0)
        # drag top left corner
        self.display_panel.display_canvas_item.simulate_drag((500,250), (800,250))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[0]), (8, 2.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[1]), (7, 5))
        # drag with shift key
        self.display_panel.display_canvas_item.simulate_drag((800,250), (900,250), CanvasItem.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[0]), (9, 1.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[1]), (6, 6))

    def test_resize_nonsquare_ellipse(self):
        self.data_item = DataItem.DataItem(numpy.zeros((20, 10)))
        self.document_model.append_data_item(self.data_item)
        self.display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        self.display_panel.set_display_panel_data_item(self.data_item)
        self.display_panel.display_canvas_item.layout_immediate(Geometry.IntSize(height=2000, width=1000))
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_ellipse_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.display_specifier.display.graphics[0].bounds[1], (0.5, 0.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[0]), (5, 2.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[1]), (10, 5))
        # select it
        self.display_specifier.display.graphic_selection.set(0)
        # drag top left corner
        self.display_panel.display_canvas_item.simulate_drag((500,250), (800,250), CanvasItem.KeyboardModifiers(alt=True))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[0]), (8, 2.5))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[1]), (4, 5))
        # drag with shift key
        self.display_panel.display_canvas_item.simulate_drag((800,250), (900,250), CanvasItem.KeyboardModifiers(shift=True, alt=True))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[0]), (9, 4))
        self.assertClosePoint(self.display_panel.display_canvas_item.map_image_norm_to_image(self.display_specifier.display.graphics[0].bounds[1]), (2, 2))

    def test_insert_remove_graphics_and_selection(self):
        self.assertFalse(self.display_specifier.display.graphic_selection.indexes)
        self.document_controller.add_rectangle_graphic()
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_specifier.display.graphic_selection.indexes)
        graphic = Graphics.RectangleGraphic()
        graphic.bounds = ((0.5,0.5), (0.25,0.25))
        self.display_specifier.display.insert_graphic(0, graphic)
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(1 in self.display_specifier.display.graphic_selection.indexes)
        self.display_specifier.display.remove_graphic(self.display_specifier.display.graphics[0])
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.display_specifier.display.graphic_selection.indexes)

    def test_delete_key_when_graphic_selected_removes_the_graphic(self):
        self.document_controller.add_rectangle_graphic()
        modifiers = CanvasItem.KeyboardModifiers()
        # focus click
        self.display_panel.root_container.canvas_widget.simulate_mouse_click(500, 500, modifiers)  # click on graphic
        # check assumptions
        self.assertEqual(len(self.display_specifier.display.graphics), 1)
        self.assertEqual(len(self.display_specifier.display.graphic_selection.indexes), 1)
        # do focusing click, then delete
        self.display_panel.root_container.canvas_widget.on_key_pressed(TestUI.Key(None, "delete", modifiers))
        # check results
        self.assertEqual(len(self.display_specifier.display.graphics), 0)

    def test_delete_key_when_nothing_selected_does_nothing(self):
        modifiers = CanvasItem.KeyboardModifiers()
        # check assumptions
        self.assertIsNotNone(self.display_panel.data_item)
        # do focusing click, then delete
        self.display_panel.root_container.canvas_widget.simulate_mouse_click(100, 100, modifiers)
        self.display_panel.root_container.canvas_widget.on_key_pressed(TestUI.Key(None, "delete", modifiers))
        # check results
        self.assertIsNotNone(self.display_panel.data_item)

    def test_line_plot_initially_displays_entire_data_in_horizontal_direction(self):
        line_plot_canvas_item = self.setup_line_plot()
        self.assertEqual(line_plot_canvas_item.line_graph_canvas_item._axes.drawn_left_channel, 0)
        self.assertEqual(line_plot_canvas_item.line_graph_canvas_item._axes.drawn_right_channel, 1024)

    def test_line_plot_initially_displays_entire_data_in_vertical_direction(self):
        line_plot_canvas_item = self.setup_line_plot()
        self.assertEqual(line_plot_canvas_item.line_graph_canvas_item._axes.uncalibrated_data_min, 0.0)
        self.assertEqual(line_plot_canvas_item.line_graph_canvas_item._axes.uncalibrated_data_max, 1.0)

    def test_mouse_tracking_moves_horizontal_scale(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_horizontal(Geometry.IntPoint(x=320, y=465), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=360, y=465), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        offset = -1024.0 * 40.0 / plot_width
        self.assertEqual(self.display_specifier.display.left_channel, int(offset))
        self.assertEqual(self.display_specifier.display.right_channel, int(1024 + offset))

    def test_mouse_tracking_moves_vertical_scale(self):
        line_plot_canvas_item = self.setup_line_plot()
        # notice: dragging increasing y drags down.
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        offset = -1.0 * 30.0 / plot_height
        self.assertAlmostEqual(self.display_specifier.display.y_min, 0.0 + offset)
        self.assertAlmostEqual(self.display_specifier.display.y_max, 1.0 + offset)

    def test_mouse_tracking_moves_vertical_scale_with_calibrated_data_with_offset(self):
        # notice: dragging increasing y drags down.
        line_plot_canvas_item = self.setup_line_plot()
        data_item = self.display_specifier.data_item
        intensity_calibration = data_item.intensity_calibration
        intensity_calibration.offset = 0.2
        data_item.set_intensity_calibration(intensity_calibration)
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        calibrated_data_min = line_plot_canvas_item.line_graph_canvas_item._axes.calibrated_data_min
        calibrated_data_max = line_plot_canvas_item.line_graph_canvas_item._axes.calibrated_data_max
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        uncalibrated_data_min = line_plot_canvas_item.line_graph_canvas_item._axes.uncalibrated_data_min
        uncalibrated_data_max = line_plot_canvas_item.line_graph_canvas_item._axes.uncalibrated_data_max
        uncalibrated_data_range = uncalibrated_data_max - uncalibrated_data_min
        offset = -uncalibrated_data_range * 30.0 / plot_height
        self.assertAlmostEqual(self.display_specifier.display.y_min, calibrated_data_min + offset - intensity_calibration.offset)
        self.assertAlmostEqual(self.display_specifier.display.y_max, calibrated_data_max + offset - intensity_calibration.offset)

    def test_mouse_tracking_moves_log_vertical_scale_with_uncalibrated_data(self):
        # notice: dragging increasing y drags down.
        line_plot_canvas_item = self.setup_line_plot(data_min=0.1, data_max=980)
        self.display_specifier.display.y_style = "log"
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        calibrated_data_min = line_plot_canvas_item.line_graph_canvas_item._axes.calibrated_data_min
        calibrated_data_max = line_plot_canvas_item.line_graph_canvas_item._axes.calibrated_data_max
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        axes = line_plot_canvas_item.line_graph_canvas_item._axes
        calibrated_data_range = calibrated_data_max - calibrated_data_min
        calibrated_offset = -calibrated_data_range * 30.0 / plot_height
        self.assertAlmostEqual(self.display_specifier.display.y_min, axes.uncalibrate_y(calibrated_data_min + calibrated_offset))
        self.assertAlmostEqual(self.display_specifier.display.y_max, axes.uncalibrate_y(calibrated_data_max + calibrated_offset))

    def test_mouse_tracking_moves_log_vertical_scale_with_calibrated_data_with_offset(self):
        # notice: dragging increasing y drags down.
        line_plot_canvas_item = self.setup_line_plot(data_min=0.1, data_max=980)
        self.display_specifier.display.y_style = "log"
        data_item = self.display_specifier.data_item
        intensity_calibration = data_item.intensity_calibration
        intensity_calibration.offset = 0.2
        data_item.set_intensity_calibration(intensity_calibration)
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        calibrated_data_min = line_plot_canvas_item.line_graph_canvas_item._axes.calibrated_data_min
        calibrated_data_max = line_plot_canvas_item.line_graph_canvas_item._axes.calibrated_data_max
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        axes = line_plot_canvas_item.line_graph_canvas_item._axes
        calibrated_data_range = calibrated_data_max - calibrated_data_min
        calibrated_offset = -calibrated_data_range * 30.0 / plot_height
        self.assertAlmostEqual(self.display_specifier.display.y_min, axes.uncalibrate_y(calibrated_data_min + calibrated_offset))
        self.assertAlmostEqual(self.display_specifier.display.y_max, axes.uncalibrate_y(calibrated_data_max + calibrated_offset))

    def test_mouse_tracking_moves_log_vertical_scale_with_calibrated_data_with_offset_and_scale(self):
        # notice: dragging increasing y drags down.
        line_plot_canvas_item = self.setup_line_plot(data_min=0.1, data_max=980)
        self.display_specifier.display.y_style = "log"
        data_item = self.display_specifier.data_item
        intensity_calibration = data_item.intensity_calibration
        intensity_calibration.offset = 0.2
        intensity_calibration.scale = 1.6
        data_item.set_intensity_calibration(intensity_calibration)
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        calibrated_data_min = line_plot_canvas_item.line_graph_canvas_item._axes.calibrated_data_min
        calibrated_data_max = line_plot_canvas_item.line_graph_canvas_item._axes.calibrated_data_max
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        axes = line_plot_canvas_item.line_graph_canvas_item._axes
        calibrated_data_range = calibrated_data_max - calibrated_data_min
        calibrated_offset = -calibrated_data_range * 30.0 / plot_height
        self.assertAlmostEqual(self.display_specifier.display.y_min, axes.uncalibrate_y(calibrated_data_min + calibrated_offset))
        self.assertAlmostEqual(self.display_specifier.display.y_max, axes.uncalibrate_y(calibrated_data_max + calibrated_offset))

    def test_mouse_tracking_shrink_scale_by_10_around_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=-96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        self.assertEqual(self.display_specifier.display.left_channel, int(round(512 - int(plot_width * 0.5) * 10 * channel_per_pixel)))
        self.assertEqual(self.display_specifier.display.right_channel, int(round(512 + int(plot_width * 0.5) * 10 * channel_per_pixel)))

    def test_mouse_tracking_expand_scale_by_10_around_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        # self.__display.left_channel = int(round(self.__tracking_start_channel - new_drawn_channel_per_pixel * self.__tracking_start_origin_pixel))
        self.assertEqual(self.display_specifier.display.left_channel, int(round(512 - int(plot_width * 0.5) * 0.1 * channel_per_pixel)))
        self.assertEqual(self.display_specifier.display.right_channel, int(round(512 + int(plot_width * 0.5) * 0.1 * channel_per_pixel)))

    def test_mouse_tracking_expand_scale_by_high_amount(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
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
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
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
        self.document_model.data_items[1].displays[0].add_graphic(interval_graphic)
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
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
        self.document_model.data_items[1].displays[0].add_graphic(interval_graphic)
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
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
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + 200, y=465)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=-96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        self.assertEqual(self.display_specifier.display.left_channel, int(round(200 * channel_per_pixel - 200 * 10 * channel_per_pixel)))
        self.assertEqual(self.display_specifier.display.right_channel, int(round(200 * channel_per_pixel + (plot_width - 200) * 10 * channel_per_pixel)))

    def test_mouse_tracking_expand_scale_by_10_around_non_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + 400, y=465)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        self.assertEqual(self.display_specifier.display.left_channel, int(round(400 * channel_per_pixel - 400 * 0.1 * channel_per_pixel)))
        self.assertEqual(self.display_specifier.display.right_channel, int(round(400 * channel_per_pixel + (plot_width - 400) * 0.1 * channel_per_pixel)))

    def test_mouse_tracking_vertical_shrink_with_origin_at_bottom(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        pos = Geometry.IntPoint(x=30, y=plot_bottom - 200)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=40)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        scaling = float(plot_bottom - pos.y) / float(plot_bottom - (pos.y + offset.height))
        self.assertAlmostEqual(self.display_specifier.display.y_min, 0.0)
        self.assertAlmostEqual(self.display_specifier.display.y_max, scaling)

    def test_mouse_tracking_vertical_shrink_with_origin_in_middle(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.display_specifier.display.y_min = -0.5
        self.display_specifier.display.y_max = 0.5
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        # now stretch 1/2 + 100 to 1/2 + 150
        pos = Geometry.IntPoint(x=30, y=plot_bottom-320)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=50)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height/2.0) - pos.y
        scaling = float(relative_y) / float(relative_y - offset.height)
        self.assertAlmostEqual(self.display_specifier.display.y_min, -0.5 * scaling)
        self.assertAlmostEqual(self.display_specifier.display.y_max, 0.5 * scaling)

    def test_mouse_tracking_vertical_shrink_with_origin_at_200(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.display_specifier.display.y_min = -0.2
        self.display_specifier.display.y_max = 0.8
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        # now stretch 1/2 + 100 to 1/2 + 150
        pos = Geometry.IntPoint(x=30, y=plot_bottom-320)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=50)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height*0.2) - pos.y
        scaling = float(relative_y) / float(relative_y - offset.height)
        self.assertAlmostEqual(self.display_specifier.display.y_min, -0.2 * scaling)
        self.assertAlmostEqual(self.display_specifier.display.y_max, 0.8 * scaling)

    def test_mouse_tracking_vertical_shrink_with_calibrated_origin_at_200(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        data_item = self.display_specifier.data_item
        # adjust image panel display and trigger layout
        intensity_calibration = data_item.intensity_calibration
        intensity_calibration.offset = -0.2
        data_item.set_intensity_calibration(intensity_calibration)
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        # now stretch 1/2 + 100 to 1/2 + 150
        pos = Geometry.IntPoint(x=30, y=plot_bottom-320)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=50)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height*0.2) - pos.y
        scaling = float(relative_y) / float(relative_y - offset.height)
        self.assertAlmostEqual(self.display_specifier.display.y_min, -0.2 * scaling + 0.2)
        self.assertAlmostEqual(self.display_specifier.display.y_max, 0.8 * scaling + 0.2)

    def test_mouse_tracking_vertical_drag_down_does_not_go_negative(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.display_specifier.display.y_min = -0.5
        self.display_specifier.display.y_max = 0.5
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        # now stretch way past top
        pos = Geometry.IntPoint(x=30, y=20)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=plot_height)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        new_drawn_data_per_pixel = 1.0/plot_height * (plot_bottom - plot_height*0.5 - pos.y)
        self.assertAlmostEqual(self.display_specifier.display.y_min, -new_drawn_data_per_pixel * plot_height*0.5)
        self.assertAlmostEqual(self.display_specifier.display.y_max, new_drawn_data_per_pixel * plot_height*0.5)

    def test_mouse_tracking_vertical_drag_up_does_not_go_negative(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.display_specifier.display.y_min = -0.5
        self.display_specifier.display.y_max = 0.5
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        # now stretch way past top
        pos = Geometry.IntPoint(x=30, y=plot_height-20)
        modifiers = CanvasItem.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=-plot_height)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        new_drawn_data_per_pixel = -1.0/plot_height * (plot_bottom - plot_height*0.5 - pos.y)
        self.assertAlmostEqual(self.display_specifier.display.y_min, -new_drawn_data_per_pixel * plot_height*0.5)
        self.assertAlmostEqual(self.display_specifier.display.y_max, new_drawn_data_per_pixel * plot_height*0.5)

    def test_combined_horizontal_drag_and_expand_works_nominally(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        v = line_plot_canvas_item.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)[0] + 8
        line_plot_canvas_item.mouse_pressed(plot_left, v, CanvasItem.KeyboardModifiers(control=True))
        line_plot_canvas_item.mouse_position_changed(plot_left+96, v, CanvasItem.KeyboardModifiers(control=True))
        # continue
        line_plot_canvas_item.mouse_position_changed(plot_left+96, v, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_position_changed(plot_left+196, v, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+116, 190, CanvasItem.KeyboardModifiers())
        channel_per_pixel = 1024.0/10 / plot_width
        self.assertEqual(self.display_specifier.display.left_channel, int(0 - channel_per_pixel * 100))
        self.assertEqual(self.display_specifier.display.right_channel, int(int(1024/10.0) - channel_per_pixel * 100))

    def test_click_on_selection_makes_it_selected(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_specifier = DataItem.DisplaySpecifier.from_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        line_plot_display_specifier.display.add_graphic(region)
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_display_specifier.display.graphic_selection.indexes), 0)
        # do the click
        line_plot_canvas_item.mouse_pressed(plot_left+plot_width * 0.35, 100, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+plot_width * 0.35, 100, CanvasItem.KeyboardModifiers())
        # make sure results are correct
        self.assertEqual(len(line_plot_display_specifier.display.graphic_selection.indexes), 1)

    def test_click_outside_selection_makes_it_unselected(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_specifier = DataItem.DisplaySpecifier.from_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        line_plot_display_specifier.display.add_graphic(region)
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_display_specifier.display.graphic_selection.indexes), 0)
        # do the first click to select
        line_plot_canvas_item.mouse_pressed(plot_left+plot_width * 0.35, 100, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+plot_width * 0.35, 100, CanvasItem.KeyboardModifiers())
        # make sure results are correct
        self.assertEqual(len(line_plot_display_specifier.display.graphic_selection.indexes), 1)
        # do the second click to deselect
        line_plot_canvas_item.mouse_pressed(plot_left+plot_width * 0.1, 100, CanvasItem.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+plot_width * 0.1, 100, CanvasItem.KeyboardModifiers())
        # make sure results are correct
        self.assertEqual(len(line_plot_display_specifier.display.graphic_selection.indexes), 0)

    def test_click_drag_interval_end_channel_to_right_adjust_end_channel(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_specifier = DataItem.DisplaySpecifier.from_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        line_plot_display_specifier.display.add_graphic(region)
        # select, then click drag
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.4, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.5, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.5, 100, modifiers)
        # make sure results are correct
        line_plot_canvas_item.root_container.refresh_layout_immediate()
        self.assertAlmostEqual(line_plot_display_specifier.display.graphics[0].start, 0.3)
        self.assertAlmostEqual(line_plot_display_specifier.display.graphics[0].end, 0.5)

    def test_click_drag_interval_end_channel_to_left_of_start_channel_results_in_left_less_than_right(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_specifier = DataItem.DisplaySpecifier.from_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        DataItem.DisplaySpecifier.from_data_item(line_plot_data_item).display.add_graphic(region)
        # select, then click drag
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.4, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.2, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.2, 100, modifiers)
        # make sure results are correct
        self.assertAlmostEqual(line_plot_display_specifier.display.graphics[0].start, 0.2, 2)  # pixel accuracy, approx. 1/500
        self.assertAlmostEqual(line_plot_display_specifier.display.graphics[0].end, 0.3, 2)  # pixel accuracy, approx. 1/500

    def test_click_drag_interval_tool_creates_selection(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_specifier = DataItem.DisplaySpecifier.from_data_item(line_plot_data_item)
        self.document_controller.tool_mode = "interval"
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_display_specifier.display.graphics), 0)
        # click drag
        modifiers = CanvasItem.KeyboardModifiers()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.40, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.50, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.50, 100, modifiers)
        # make sure results are correct
        self.assertEqual(len(line_plot_display_specifier.display.graphics), 1)
        self.assertTrue(isinstance(line_plot_display_specifier.display.graphics[0], Graphics.IntervalGraphic))
        self.assertAlmostEqual(line_plot_display_specifier.display.graphics[0].start, 0.35, 2)  # pixel accuracy, approx. 1/500
        self.assertAlmostEqual(line_plot_display_specifier.display.graphics[0].end, 0.50, 2)  # pixel accuracy, approx. 1/500
        # and that tool is returned to pointer
        self.assertEqual(self.document_controller.tool_mode, "pointer")

    def test_delete_line_profile_with_key(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        line_plot_data_item = self.document_model.data_items[1]
        line_plot_display_specifier = DataItem.DisplaySpecifier.from_data_item(line_plot_data_item)
        region = Graphics.IntervalGraphic()
        region.start = 0.3
        region.end = 0.4
        line_plot_display_specifier.display.add_graphic(region)
        line_plot_display_specifier.display.graphic_selection.set(0)
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_display_specifier.display.graphics), 1)
        self.assertEqual(len(line_plot_display_specifier.display.graphic_selection.indexes), 1)
        # hit the delete key
        self.display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("delete"))
        self.assertEqual(len(line_plot_display_specifier.display.graphics), 0)

    def test_key_gets_dispatched_to_image_canvas_item(self):
        modifiers = CanvasItem.KeyboardModifiers()
        self.display_panel.root_container.canvas_widget.simulate_mouse_click(100, 100, modifiers)
        self.display_panel.root_container.canvas_widget.on_key_pressed(TestUI.Key(None, "up", modifiers))
        # self.display_panel.display_canvas_item.key_pressed(TestUI.Key(None, "up", modifiers))  # direct dispatch, should work
        self.assertEqual(self.display_panel.display_canvas_item.scroll_area_canvas_item.content.canvas_rect, ((-10, 0), (1000, 1000)))

    def test_drop_on_overlay_middle_triggers_replace_data_item_in_panel_action(self):
        width, height = 640, 480
        display_panel = TestDisplayPanel()
        overlay = DisplayPanel.DisplayPanelOverlayCanvasItem()
        overlay.on_drag_enter = display_panel.handle_drag_enter
        overlay.on_drag_move = display_panel.handle_drag_move
        overlay.on_drop = display_panel.handle_drop
        overlay.update_layout((0, 0), (height, width), immediate=True)
        mime_data = None
        overlay.drag_enter(mime_data)
        overlay.drag_move(mime_data, int(width*0.5), int(height*0.5))
        overlay.drop(mime_data, int(width*0.5), int(height*0.5))
        self.assertEqual(display_panel.drop_region, "middle")

    def test_replacing_display_actually_does_it(self):
        self.assertEqual(self.display_panel.data_item, self.data_item)
        self.display_panel.set_display_panel_data_item(self.data_item)
        data_item_1d = DataItem.DataItem(create_1d_data())
        self.document_model.append_data_item(data_item_1d)
        self.display_panel.set_display_panel_data_item(data_item_1d)
        self.assertEqual(self.display_panel.data_item, data_item_1d)

    def test_drop_on_overlay_edge_triggers_split_image_panel_action(self):
        width, height = 640, 480
        display_panel = TestDisplayPanel()
        overlay = DisplayPanel.DisplayPanelOverlayCanvasItem()
        overlay.on_drag_enter = display_panel.handle_drag_enter
        overlay.on_drag_move = display_panel.handle_drag_move
        overlay.on_drop = display_panel.handle_drop
        overlay.update_layout((0, 0), (height, width), immediate=True)
        mime_data = None
        overlay.drag_enter(mime_data)
        overlay.drag_move(mime_data, int(width*0.05), int(height*0.5))
        overlay.drop(mime_data, int(width*0.05), int(height*0.5))
        self.assertEqual(display_panel.drop_region, "left")

    def test_replace_displayed_data_item_and_display_detects_default_raster_display(self):
        self.display_panel.set_display_panel_data_item(self.data_item)
        self.assertEqual(self.display_panel.data_item, self.data_item)

    def test_1d_data_with_zero_dimensions_display_fails_without_exception(self):
        self.data_item.set_data(numpy.zeros((0, )))
        # display panel should not have any display_canvas_item now since data is not valid
        self.assertIsInstance(self.display_panel.display_canvas_item, DisplayPanel.MissingDataCanvasItem)
        # thumbnails and processors
        with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, self.display_specifier.display)) as thumbnail_source:
            thumbnail_source.recompute_data()
            self.assertIsNotNone(thumbnail_source.thumbnail_data)
        self.document_controller.periodic()
        self.document_controller.document_model.recompute_all()

    def test_2d_data_with_zero_dimensions_display_fails_without_exception(self):
        self.data_item.set_data(numpy.zeros((0, 0)))
        # display panel should not have any display_canvas_item now since data is not valid
        self.assertIsInstance(self.display_panel.display_canvas_item, DisplayPanel.MissingDataCanvasItem)
        # thumbnails and processors
        with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, self.display_specifier.display)) as thumbnail_source:
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
        self.assertEqual(len(self.display_specifier.display.graphics), 1)
        region = self.display_specifier.display.graphics[0]
        self.assertEqual(region.type, "point-graphic")
        self.assertAlmostEqual(region.position[0], 0.2)
        self.assertAlmostEqual(region.position[1], 0.25)

    def test_dragging_to_add_rectangle_makes_desired_rectangle(self):
        self.document_controller.tool_mode = "rectangle"
        self.display_panel.display_canvas_item.simulate_drag((100,125), (250,200))
        self.assertEqual(len(self.display_specifier.display.graphics), 1)
        region = self.display_specifier.display.graphics[0]
        self.assertEqual(region.type, "rect-graphic")
        self.assertAlmostEqual(region.bounds[0][0], 0.1)
        self.assertAlmostEqual(region.bounds[0][1], 0.125)
        self.assertAlmostEqual(region.bounds[1][0], 0.15)
        self.assertAlmostEqual(region.bounds[1][1], 0.075)

    def test_dragging_to_add_ellipse_makes_desired_ellipse(self):
        self.document_controller.tool_mode = "ellipse"
        self.display_panel.display_canvas_item.simulate_drag((100,125), (250,200))
        self.assertEqual(len(self.display_specifier.display.graphics), 1)
        region = self.display_specifier.display.graphics[0]
        self.assertEqual(region.type, "ellipse-graphic")
        self.assertAlmostEqual(region.bounds[0][0], 0.1)
        self.assertAlmostEqual(region.bounds[0][1], 0.125)
        self.assertAlmostEqual(region.bounds[1][0], 0.15)
        self.assertAlmostEqual(region.bounds[1][1], 0.075)

    def test_dragging_to_add_line_makes_desired_line(self):
        self.document_controller.tool_mode = "line"
        self.display_panel.display_canvas_item.simulate_drag((100,125), (200,250))
        self.assertEqual(len(self.display_specifier.display.graphics), 1)
        region = self.display_specifier.display.graphics[0]
        self.assertEqual(region.type, "line-graphic")
        self.assertAlmostEqual(region.start[0], 0.1)
        self.assertAlmostEqual(region.start[1], 0.125)
        self.assertAlmostEqual(region.end[0], 0.2)
        self.assertAlmostEqual(region.end[1], 0.25)

    def test_dragging_to_add_line_profile_makes_desired_line_profile(self):
        self.document_controller.tool_mode = "line-profile"
        self.display_panel.display_canvas_item.simulate_drag((100,125), (200,250))
        self.assertEqual(len(self.display_specifier.display.graphics), 1)
        region = self.display_specifier.display.graphics[0]
        self.assertEqual(region.type, "line-profile-graphic")
        self.assertAlmostEqual(region.start[0], 0.1)
        self.assertAlmostEqual(region.start[1], 0.125)
        self.assertAlmostEqual(region.end[0], 0.2)
        self.assertAlmostEqual(region.end[1], 0.25)

    def test_dragging_to_add_line_profile_works_when_line_profile_is_filtered_from_data_panel(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
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
            display_panel.set_display_panel_data_item(data_item)
            root_canvas_item.update_layout(Geometry.IntPoint(), Geometry.IntSize(width=1000, height=500 + header_height), immediate=True)
            document_controller.set_filter("none")
            document_controller.tool_mode = "line-profile"
            display_panel.display_canvas_item.simulate_drag((100,125), (200,250))
            display = data_item.displays[0]
            self.assertEqual(len(display.graphics), 1)
            region = display.graphics[0]
            self.assertEqual(region.type, "line-profile-graphic")
            self.assertAlmostEqual(0.2, region.start[0])
            self.assertAlmostEqual(0.25, region.start[1])
            self.assertAlmostEqual(0.4, region.end[0])
            self.assertAlmostEqual(0.5, region.end[1])

    def test_enter_to_auto_display_limits(self):
        # test preliminary assumptions (no display limits)
        display_limits = 0.5, 1.5
        self.data_item.displays[0].display_limits = display_limits
        self.assertIsNotNone(self.display_specifier.display.display_limits)
        # focus on the display panel, then press the enter key
        modifiers = CanvasItem.KeyboardModifiers()
        self.display_panel.root_container.canvas_widget.simulate_mouse_click(100, 100, modifiers)
        self.display_panel.root_container.canvas_widget.on_key_pressed(TestUI.Key(None, "enter", modifiers))
        # confirm that display limits were set
        self.assertIsNotNone(self.data_item.displays[0].display_limits)
        self.assertNotEqual(self.data_item.displays[0].display_limits, display_limits)

    def test_image_display_panel_produces_context_menu_with_correct_item_count(self):
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.canvas_widget.on_context_menu_event(500, 500, 500, 500)
        # show, delete, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(len(self.document_controller.ui.popup.items), 14)

    def test_image_display_panel_produces_context_menu_with_correct_item_count_outside_image_area(self):
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.canvas_widget.on_context_menu_event(10, 32, 10, 32)  # header + 10
        # show, delete, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(len(self.document_controller.ui.popup.items), 14)

    def test_image_display_panel_with_no_image_produces_context_menu_with_correct_item_count(self):
        self.display_panel.set_display_panel_data_item(None)
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(500, 500, 500, 500)
        # show, delete, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(len(self.document_controller.ui.popup.items), 10)

    def test_empty_display_panel_produces_context_menu_with_correct_item_count(self):
        d = {"type": "image", "display-panel-type": "empty-display-panel"}
        self.display_panel.change_display_panel_content(d)
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(500, 500, 500, 500)
        # sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(len(self.document_controller.ui.popup.items), 10)

    def test_browser_display_panel_produces_context_menu_with_correct_item_count_over_data_item(self):
        d = {"type": "image", "display-panel-type": "browser-display-panel"}
        self.display_panel.change_display_panel_content(d)
        self.document_controller.periodic()
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(40, 40, 40, 40)
        # show, delete, sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(len(self.document_controller.ui.popup.items), 14)

    def test_browser_display_panel_produces_context_menu_with_correct_item_count_over_area_to_right_of_data_item(self):
        d = {"type": "image", "display-panel-type": "browser-display-panel"}
        self.display_panel.change_display_panel_content(d)
        self.document_controller.periodic()
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(300, 40, 300, 40)
        # sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(len(self.document_controller.ui.popup.items), 10)

    def test_browser_display_panel_produces_context_menu_with_correct_item_count_below_last_data_item(self):
        d = {"type": "image", "display-panel-type": "browser-display-panel"}
        self.display_panel.change_display_panel_content(d)
        self.document_controller.periodic()
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(300, 300, 300, 300)
        # sep, split h, split v, sep, none, sep, data, thumbnails, browser, sep
        self.assertEqual(len(self.document_controller.ui.popup.items), 10)

    def test_browser_context_menu_deletes_all_selected_items(self):
        d = {"type": "image", "display-panel-type": "browser-display-panel"}
        self.display_panel.change_display_panel_content(d)
        self.document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
        self.document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
        self.document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
        self.assertEqual(len(self.document_model.data_items), 4)
        self.document_controller.periodic()
        self.document_controller.select_data_items_in_data_panel(self.document_model.data_items)
        self.document_controller.periodic()
        self.assertIsNone(self.document_controller.ui.popup)
        self.display_panel.root_container.refresh_layout_immediate()
        self.display_panel.root_container.canvas_widget.on_context_menu_event(40, 40, 40, 40)
        self.document_controller.periodic()
        # show, reveal, delete, sep, split h, split v, sep, none, sep, browser, sep
        self.document_controller.ui.popup.items[2].callback()
        self.assertEqual(len(self.document_model.data_items), 0)

    def test_display_panel_title_gets_updated_when_data_item_title_is_changed(self):
        self.assertEqual(self.display_panel.header_canvas_item.title, self.data_item.displayed_title)
        self.data_item.title = "New Title"
        self.document_controller.periodic()
        self.assertEqual(self.display_panel.header_canvas_item.title, self.data_item.displayed_title)

    def test_display_panel_title_gets_updated_when_data_item_r_value_is_changed(self):
        self.assertEqual(self.display_panel.header_canvas_item.title, self.data_item.displayed_title)
        self.data_item.set_r_value("r111")
        self.document_controller.periodic()
        self.assertEqual(self.display_panel.header_canvas_item.title, self.data_item.displayed_title)

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
        self.display_panel.display_canvas_item.prepare_display()  # force layout
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

    def test_all_graphic_types_hit_test_on_2d_display(self):
        self.document_controller.add_point_graphic()
        self.document_controller.add_line_graphic()
        self.document_controller.add_rectangle_graphic()
        self.document_controller.add_ellipse_graphic()
        self.document_controller.add_interval_graphic()
        self.display_panel.display_canvas_item.prepare_display()  # force layout
        self.display_panel.display_canvas_item.mouse_pressed(10, 10, CanvasItem.KeyboardModifiers())
        self.display_panel.display_canvas_item.mouse_released(10, 10, CanvasItem.KeyboardModifiers())

    def test_all_graphic_types_hit_test_on_3d_display(self):
        display_canvas_item = self.setup_3d_data()
        self.document_controller.add_point_graphic()
        self.document_controller.add_line_graphic()
        self.document_controller.add_rectangle_graphic()
        self.document_controller.add_ellipse_graphic()
        self.document_controller.add_interval_graphic()
        display_canvas_item.mouse_pressed(10, 10, CanvasItem.KeyboardModifiers())
        display_canvas_item.mouse_released(10, 10, CanvasItem.KeyboardModifiers())

    def test_display_2d_update_with_no_data(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item1 = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
            document_model.append_data_item(data_item1)
            data_item = document_model.get_crop_new(data_item1)
            data_item.displays[0].display_type = "line_plot"
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            document_controller.periodic()

    def test_display_2d_collection_with_2d_datum_displays_image(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem()
            data_item.ensure_data_source()
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(numpy.ones((2, 2, 8, 8)), data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate(Geometry.IntSize(1000 + header_height, 1000))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)

    def test_image_display_canvas_item_only_updates_if_display_data_changes(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 240))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)
            display = data_item.displays[0]
            update_count = display_panel.display_canvas_item._update_count
            document_controller.periodic()
            self.assertEqual(update_count, display_panel.display_canvas_item._update_count)

    def test_image_display_canvas_item_only_updates_once_if_data_changes(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 240))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)
            update_count = display_panel.display_canvas_item._update_count
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(numpy.random.randn(8, 8)))
            self.assertEqual(update_count + 1, display_panel.display_canvas_item._update_count)

    def test_image_display_canvas_item_only_updates_once_if_graphic_changes(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            graphic = Graphics.RectangleGraphic()
            data_item.displays[0].add_graphic(graphic)
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 240))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)
            update_count = display_panel.display_canvas_item._update_count
            graphic.bounds = Geometry.FloatRect.from_tlbr(0.1, 0.1, 0.2, 0.2)
            self.assertEqual(update_count + 1, display_panel.display_canvas_item._update_count)

    def test_line_plot_image_display_canvas_item_only_updates_if_display_data_changes(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 640))
            document_controller.periodic()
            self.assertIsInstance(display_panel.display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)
            display = data_item.displays[0]
            update_count = display_panel.display_canvas_item._update_count
            document_controller.periodic()
            self.display_panel.root_container.refresh_layout_immediate()
            self.assertEqual(update_count, display_panel.display_canvas_item._update_count)

    def test_focused_data_item_changes_when_display_changed_directly_in_content(self):
        # this capability is only used in the camera plug-in when switching image to summed and back.
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item2)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            self.assertEqual(data_item, document_controller.focused_data_item)
            display_panel._select()
            self.assertEqual(data_item, document_controller.focused_data_item)
            display_panel.set_displayed_data_item(data_item2)
            self.assertEqual(data_item2, document_controller.focused_data_item)

    def test_composite_library_item_produces_composite_display(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item2)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item1)
            composite_item.append_data_item(data_item2)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(composite_item)
            self.assertIsInstance(display_panel._display_canvas_item, DisplayPanel.CompositeDisplayCanvasItem)

    def test_changing_display_type_of_composite_updates_displays_in_canvas_item(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item1)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item1)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(composite_item)
            composite_display = display_panel._display_canvas_item
            self.assertSequenceEqual(data_item1.displays, composite_display._displays)
            composite_item.displays[0].display_type = "line_plot"
            self.assertNotEqual(composite_display, display_panel._display_canvas_item)
            composite_item.displays[0].display_type = None
            composite_display = display_panel._display_canvas_item
            self.assertSequenceEqual(data_item1.displays, composite_display._displays)

    def test_changing_display_type_of_child_updates_composite_display(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.random.randn(8, 8))
            data_item1.displays[0].display_type = "image"
            document_model.append_data_item(data_item1)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item1)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(composite_item)
            composite_display = display_panel._display_canvas_item
            self.assertSequenceEqual(data_item1.displays, composite_display._displays)
            data_item1.displays[0].display_type = "line_plot"
            composite_display = display_panel._display_canvas_item
            self.assertSequenceEqual(data_item1.displays, composite_display._displays)

    def test_composite_item_deletes_cleanly_when_displayed(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item)
            data_item.source = composite_item
            self.assertEqual(len(document_model.data_items), 2)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(composite_item)
            document_model.remove_data_item(composite_item)
            self.assertEqual(len(document_model.data_items), 0)

    def test_dependency_icons_updated_properly_when_one_of_two_dependents_are_removed(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.zeros((100, )))
            document_model.append_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            document_model.get_crop_new(data_item)
            document_model.get_line_profile_new(data_item)
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(data_item.displays[0].graphics))
            self.assertEqual(2, len(document_model.get_dependent_items(data_item)))
            display_panel.set_display_panel_data_item(data_item)
            self.assertEqual(2, len(display_panel._related_icons_canvas_item._dependent_thumbnails.canvas_items))
            data_item.displays[0].remove_graphic(data_item.displays[0].graphics[1])
            self.assertEqual(1, len(display_panel._related_icons_canvas_item._dependent_thumbnails.canvas_items))

    def test_dragging_to_create_interval_undo_redo_cycle(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 640))
            display_panel.display_canvas_item.prepare_display()  # force layout
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            self.assertEqual(0, len(data_item.displays[0].graphics))
            self.assertIsInstance(display_panel.display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)
            line_plot_canvas_item = display_panel.display_canvas_item
            line_plot_canvas_item._mouse_dragged(0.35, 0.55)
            # check the undo status
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            for i in range(2):
                # try the undo
                document_controller.handle_undo()
                self.assertEqual(0, len(data_item.displays[0].graphics))
                self.assertFalse(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the redo
                document_controller.handle_redo()
                self.assertEqual(1, len(data_item.displays[0].graphics))
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertFalse(document_controller._undo_stack.can_redo)

    def test_dragging_to_change_interval_undo_redo_cycle(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8))
            interval_graphic = Graphics.IntervalGraphic()
            interval_graphic.start = 0.3
            interval_graphic.end = 0.5
            data_item.displays[0].add_graphic(interval_graphic)
            data_item.displays[0].graphic_selection.set(0)
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.prepare_display()  # force layout
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertIsInstance(display_panel.display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)
            line_plot_canvas_item = display_panel.display_canvas_item
            line_plot_canvas_item._mouse_dragged(0.4, 0.5)
            # check the undo status. use full object specifiers since objects may be replaced.
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertAlmostEqual(0.4, data_item.displays[0].graphics[0].interval[0], 1)
            self.assertAlmostEqual(0.6, data_item.displays[0].graphics[0].interval[1], 1)
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            for i in range(2):
                # try the undo
                document_controller.handle_undo()
                self.assertEqual(1, len(data_item.displays[0].graphics))
                self.assertAlmostEqual(0.3, data_item.displays[0].graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.5, data_item.displays[0].graphics[0].interval[1], 1)
                self.assertFalse(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the redo
                document_controller.handle_redo()
                self.assertEqual(1, len(data_item.displays[0].graphics))
                self.assertAlmostEqual(0.4, data_item.displays[0].graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.6, data_item.displays[0].graphics[0].interval[1], 1)
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertFalse(document_controller._undo_stack.can_redo)

    def test_display_undo_invalidated_with_external_change(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.random.randn(8))
            interval_graphic = Graphics.IntervalGraphic()
            interval_graphic.start = 0.3
            interval_graphic.end = 0.5
            data_item.displays[0].add_graphic(interval_graphic)
            data_item.displays[0].graphic_selection.set(0)
            document_model.append_data_item(data_item)
            self.assertEqual(1, len(data_item.displays[0].graphics))
            command = DisplayPanel.ChangeGraphicsCommand(document_model, data_item.displays[0], [interval_graphic])
            data_item.displays[0].graphics[0].interval = 0.4, 0.6
            document_controller.push_undo_command(command)
            # check the undo status. use full object specifiers since objects may be replaced.
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertAlmostEqual(0.4, data_item.displays[0].graphics[0].interval[0], 1)
            self.assertAlmostEqual(0.6, data_item.displays[0].graphics[0].interval[1], 1)
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            # external change
            data_item.displays[0].graphics[0].interval = (0.3, 0.5)
            document_controller._undo_stack.validate()
            self.assertFalse(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            # make another change, make sure stack is cleared
            command = DisplayPanel.ChangeGraphicsCommand(document_model, data_item.displays[0], [interval_graphic])
            data_item.displays[0].graphics[0].interval = 0.4, 0.6
            document_controller.push_undo_command(command)
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            self.assertEqual(1, document_controller._undo_stack._undo_count)
            self.assertEqual(0, document_controller._undo_stack._redo_count)

    def test_dragging_to_create_and_change_interval_undo_redo_cycle(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.prepare_display()  # force layout
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            self.assertEqual(0, len(data_item.displays[0].graphics))
            self.assertIsInstance(display_panel.display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)
            line_plot_canvas_item = display_panel.display_canvas_item
            line_plot_canvas_item._mouse_dragged(0.3, 0.5)
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertAlmostEqual(0.3, data_item.displays[0].graphics[0].interval[0], 1)
            self.assertAlmostEqual(0.5, data_item.displays[0].graphics[0].interval[1], 1)
            line_plot_canvas_item._mouse_dragged(0.4, 0.5)
            # check the undo status. use full object specifiers since objects may be replaced.
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertAlmostEqual(0.4, data_item.displays[0].graphics[0].interval[0], 1)
            self.assertAlmostEqual(0.6, data_item.displays[0].graphics[0].interval[1], 1)
            self.assertTrue(document_controller._undo_stack.can_undo)
            self.assertFalse(document_controller._undo_stack.can_redo)
            for i in range(2):
                # try the first undo
                document_controller.handle_undo()
                self.assertEqual(1, len(data_item.displays[0].graphics))
                self.assertAlmostEqual(0.3, data_item.displays[0].graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.5, data_item.displays[0].graphics[0].interval[1], 1)
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the second undo
                document_controller.handle_undo()
                self.assertEqual(0, len(data_item.displays[0].graphics))
                self.assertFalse(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the first redo
                document_controller.handle_redo()
                self.assertEqual(1, len(data_item.displays[0].graphics))
                self.assertAlmostEqual(0.3, data_item.displays[0].graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.5, data_item.displays[0].graphics[0].interval[1], 1)
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertTrue(document_controller._undo_stack.can_redo)
                # try the second redo
                document_controller.handle_redo()
                self.assertEqual(1, len(data_item.displays[0].graphics))
                self.assertAlmostEqual(0.4, data_item.displays[0].graphics[0].interval[0], 1)
                self.assertAlmostEqual(0.6, data_item.displays[0].graphics[0].interval[1], 1)
                self.assertTrue(document_controller._undo_stack.can_undo)
                self.assertFalse(document_controller._undo_stack.can_redo)

    def test_display_undo_display_changes_command_merges_repeated_commands(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            data_item.displays[0].y_min = 0
            data_item.displays[0].y_max = 5
            y_min = data_item.displays[0].y_min
            y_max = data_item.displays[0].y_max
            for i in range(3):
                command = DisplayPanel.ChangeDisplayCommand(document_controller.document_model, data_item.displays[0], command_id="y", is_mergeable=True)
                data_item.displays[0].y_min += 1
                data_item.displays[0].y_max += 1
                document_controller.push_undo_command(command)
                self.assertEqual(1, document_controller._undo_stack._undo_count)
            document_controller.handle_undo()
            self.assertEqual(0, document_controller._undo_stack._undo_count)
            self.assertEqual(y_min, data_item.displays[0].y_min)
            self.assertEqual(y_max, data_item.displays[0].y_max)

    def test_remove_graphics_undo_redo_cycle(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item)
            interval_graphic1 = Graphics.IntervalGraphic()
            interval_graphic1.start = 0.1
            interval_graphic1.end = 0.4
            interval_graphic2 = Graphics.IntervalGraphic()
            interval_graphic2.start = 0.6
            interval_graphic2.end = 0.9
            data_item.displays[0].add_graphic(interval_graphic1)
            data_item.displays[0].add_graphic(interval_graphic2)
            data_item.displays[0].graphic_selection.set(0)
            data_item.displays[0].graphic_selection.add(1)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.prepare_display()  # force layout
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            # verify setup
            self.assertEqual(2, len(data_item.displays[0].graphics))
            # do the delete
            document_controller.remove_selected_graphics()
            self.assertEqual(0, len(data_item.displays[0].graphics))
            # do the undo and verify
            document_controller.handle_undo()
            self.assertEqual(2, len(data_item.displays[0].graphics))
            # do the redo and verify
            document_controller.handle_redo()
            self.assertEqual(0, len(data_item.displays[0].graphics))

    def test_remove_graphics_with_dependent_data_item_display_undo_redo_cycle(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item)
            line_plot_data_item = document_model.get_line_profile_new(data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(line_plot_data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.prepare_display()  # force layout
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            # verify setup
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertEqual(line_plot_data_item, display_panel.data_item)
            # do the delete
            command = document_controller.create_remove_graphics_command(data_item.displays[0], data_item.displays[0].graphics)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(0, len(data_item.displays[0].graphics))
            self.assertEqual(None, display_panel.data_item)
            # do the undo and verify
            document_controller.handle_undo()
            line_plot_data_item = document_model.data_items[1]
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertEqual(line_plot_data_item, display_panel.data_item)
            # do the redo and verify
            document_controller.handle_redo()
            self.assertEqual(0, len(data_item.displays[0].graphics))
            self.assertEqual(None, display_panel.data_item)

    def test_remove_data_item_with_dependent_data_item_display_undo_redo_cycle(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item)
            line_plot_data_item = document_model.get_line_profile_new(data_item)
            document_model.recompute_all()
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(line_plot_data_item)
            display_panel.root_container.layout_immediate(Geometry.IntSize(240, 1000))
            display_panel.display_canvas_item.prepare_display()  # force layout
            display_panel.display_canvas_item.refresh_layout_immediate()
            document_controller.periodic()
            # verify setup
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertEqual(line_plot_data_item, display_panel.data_item)
            # do the delete
            command = document_controller.create_remove_library_items_command([line_plot_data_item])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(0, len(data_item.displays[0].graphics))
            self.assertEqual(None, display_panel.data_item)
            # do the undo and verify
            document_controller.handle_undo()
            line_plot_data_item = document_model.data_items[1]
            self.assertEqual(1, len(data_item.displays[0].graphics))
            self.assertEqual(line_plot_data_item, display_panel.data_item)
            # do the redo and verify
            document_controller.handle_redo()
            self.assertEqual(0, len(data_item.displays[0].graphics))
            self.assertEqual(None, display_panel.data_item)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
