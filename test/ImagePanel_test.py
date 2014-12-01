# standard libraries
import logging
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import ImagePanel
from nion.swift import Panel
from nion.swift.model import Display
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Region
from nion.swift.model import Storage
from nion.ui import CanvasItem
from nion.ui import Geometry
from nion.ui import Test


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


class TestImagePanel(object):
    def __init__(self):
        self.drop_region = None
    def handle_drag_enter(self, mime_data):
        return "copy"
    def handle_drag_move(self, mime_data, x, y):
        return "copy"
    def handle_drop(self, mime_data, region, x, y):
        self.drop_region = region
        return "copy"


class TestImagePanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)
        self.document_model = DocumentModel.DocumentModel()
        self.document_controller = DocumentController.DocumentController(self.app.ui, self.document_model, workspace_id="library")
        self.image_panel = self.document_controller.selected_image_panel
        self.data_item = self.document_model.set_data_by_key("test", numpy.zeros((1000, 1000)))
        self.image_panel.set_displayed_data_item(self.data_item)
        header_height = Panel.HeaderCanvasItem().header_height
        self.image_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)

    def tearDown(self):
        self.document_controller.close()

    def simulate_click(self, p, modifiers=None):
        modifiers = Test.KeyboardModifiers() if not modifiers else modifiers
        self.image_panel.display_canvas_item.mouse_pressed(p[1], p[0], modifiers)
        self.image_panel.display_canvas_item.mouse_released(p[1], p[0], modifiers)

    def simulate_drag(self, p1, p2, modifiers=None):
        modifiers = Test.KeyboardModifiers() if not modifiers else modifiers
        self.image_panel.display_canvas_item.mouse_pressed(p1[1], p1[0], modifiers)
        self.image_panel.display_canvas_item.mouse_position_changed(p1[1], p1[0], modifiers)
        midp = Geometry.midpoint(p1, p2)
        self.image_panel.display_canvas_item.mouse_position_changed(midp[1], midp[0], modifiers)
        self.image_panel.display_canvas_item.mouse_position_changed(p2[1], p2[0], modifiers)
        self.image_panel.display_canvas_item.mouse_released(p2[1], p2[0], modifiers)

    def test_image_panel_gets_destructed(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        image_panel = ImagePanel.ImagePanel(document_controller)
        # add some extra refs for fun
        canvas_item = image_panel.canvas_item
        container = CanvasItem.SplitterCanvasItem()
        container.add_canvas_item(canvas_item)
        root_canvas_item = CanvasItem.RootCanvasItem(self.app.ui)
        root_canvas_item.add_canvas_item(container)
        # now take the weakref
        image_panel_weak_ref = weakref.ref(image_panel)
        image_panel.canvas_item.close()
        image_panel.close()
        image_panel = None
        self.assertIsNone(image_panel_weak_ref())
        document_controller.close()

    # user deletes data item that is displayed. make sure we remove the display.
    def test_deleting_data_item_removes_it_from_image_panel(self):
        self.assertEqual(self.image_panel.get_displayed_data_item(), self.document_model.data_items[0])
        self.assertEqual(self.image_panel.get_displayed_data_item(), self.data_item)
        self.document_controller.processing_invert()
        self.document_controller.periodic()
        self.image_panel.set_displayed_data_item(self.data_item)
        self.assertEqual(self.image_panel.get_displayed_data_item(), self.data_item)
        self.document_model.remove_data_item(self.data_item)
        self.assertIsNone(self.image_panel.get_displayed_data_item())

    # user deletes data source of data item that is displayed. make sure to remove display if source is deleted.
    def test_deleting_data_item_with_processed_data_item_removes_processed_data_item_from_image_panel(self):
        self.assertEqual(self.image_panel.get_displayed_data_item(), self.document_model.data_items[0])
        self.assertEqual(self.image_panel.get_displayed_data_item(), self.data_item)
        inverted_data_item = self.document_controller.processing_invert()
        self.document_controller.periodic()
        self.image_panel.set_displayed_data_item(inverted_data_item)
        self.assertEqual(self.image_panel.get_displayed_data_item(), inverted_data_item)
        self.document_model.remove_data_item(self.data_item)
        self.assertIsNone(self.image_panel.get_displayed_data_item())

    def test_select_line(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_region()
        # click outside so nothing is selected
        self.simulate_click((0, 0))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 0)
        # select the line
        self.simulate_click((200, 200))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.image_panel.display.graphic_selection.indexes)
        # now shift the view and try again
        self.simulate_click((0, 0))
        self.image_panel.display_canvas_item.move_left()  # 10 pixels left
        self.image_panel.display_canvas_item.move_left()  # 10 pixels left
        self.simulate_click((200, 200))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 0)
        self.simulate_click((220, 200))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.image_panel.display.graphic_selection.indexes)

    def test_select_multiple(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_region()
        self.document_controller.add_ellipse_region()
        # click outside so nothing is selected
        self.simulate_click((0, 0))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 0)
        # select the ellipse
        self.simulate_click((725, 500))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(1 in self.image_panel.display.graphic_selection.indexes)
        # select the line
        self.simulate_click((200, 200))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.image_panel.display.graphic_selection.indexes)
        # add the ellipse to the selection. click inside the right side.
        self.simulate_click((725, 500), Test.KeyboardModifiers(shift=True))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 2)
        self.assertTrue(0 in self.image_panel.display.graphic_selection.indexes)
        # remove the ellipse from the selection. click inside the right side.
        self.simulate_click((725, 500), Test.KeyboardModifiers(shift=True))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.image_panel.display.graphic_selection.indexes)

    def assertClosePoint(self, p1, p2, e=0.00001):
        self.assertTrue(Geometry.distance(p1, p2) < e)

    def assertCloseRectangle(self, r1, r2, e=0.00001):
        self.assertTrue(Geometry.distance(r1[0], r2[0]) < e and Geometry.distance(r1[1], r2[1]) < e)

    def test_drag_multiple(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_region()
        self.document_controller.add_ellipse_region()
        # make sure items are in the right place
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.data_item.displays[0].drawn_graphics[1].bounds, ((0.25, 0.25), (0.5, 0.5)))
        # select both
        self.image_panel.display.graphic_selection.set(0)
        self.image_panel.display.graphic_selection.add(1)
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 2)
        # drag by (0.1, 0.2)
        self.simulate_drag((500,500), (600,700))
        self.assertCloseRectangle(self.data_item.displays[0].drawn_graphics[1].bounds, ((0.35, 0.45), (0.5, 0.5)))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.3, 0.4))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.9, 1.0))
        # drag on endpoint (0.3, 0.4) make sure it drags all
        self.simulate_drag((300,400), (200,200))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.data_item.displays[0].drawn_graphics[1].bounds, ((0.25, 0.25), (0.5, 0.5)))
        # now select just the line, drag middle of circle. should only drag circle.
        self.image_panel.display.graphic_selection.set(0)
        self.simulate_drag((700,500), (800,500))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.data_item.displays[0].drawn_graphics[1].bounds, ((0.35, 0.25), (0.5, 0.5)))

    def test_drag_line_part(self):
        # add line (0.2, 0.2), (0.8, 0.8)
        self.document_controller.add_line_region()
        # make sure items it is in the right place
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.8, 0.8))
        # select it
        self.image_panel.display.graphic_selection.set(0)
        self.simulate_drag((200,200), (300,400))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.3, 0.4))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.8, 0.8))
        # shift drag a part, should not deselect and should align horizontally
        self.simulate_drag((300,400), (350,700), Test.KeyboardModifiers(shift=True))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.35, 0.8))
        # shift drag start to top left quadrant. check both y-maj and x-maj.
        self.simulate_drag((350,800), (370,340), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.34, 0.34))
        self.simulate_drag((340,340), (240,270), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.24, 0.24))
        # shift drag start to bottom left quadrant. check both y-maj and x-maj.
        self.simulate_drag((240,240), (370,1140), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.37, 1.23))
        self.simulate_drag((370,1230), (370,1350), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.25, 1.35))
        # shift drag start to bottom right quadrant. check both y-maj and x-maj.
        self.simulate_drag((250,1350), (1230,1175), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (1.23, 1.23))
        self.simulate_drag((1230,1230), (1150,1210), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (1.21, 1.21))
        # shift drag start to top right quadrant. check both y-maj and x-maj.
        self.simulate_drag((1210,1210), (1230,310), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (1.29, 0.31))
        self.simulate_drag((1290,310), (1110,420), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (1.18, 0.42))
        # now reverse start/end and run the same test
        self.simulate_drag((800,800), (200,200))
        self.simulate_drag((1180,420), (800,800))
        # shift drag start to top left quadrant. check both y-maj and x-maj.
        self.simulate_drag((200,200), (370,340), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.34, 0.34))
        self.simulate_drag((340,340), (240,270), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.24, 0.24))
        # shift drag start to bottom left quadrant. check both y-maj and x-maj.
        self.simulate_drag((240,240), (370,1140), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.37, 1.23))
        self.simulate_drag((370,1230), (370,1350), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (0.25, 1.35))
        # shift drag start to bottom right quadrant. check both y-maj and x-maj.
        self.simulate_drag((250,1350), (1230,1175), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (1.23, 1.23))
        self.simulate_drag((1230,1230), (1150,1210), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (1.21, 1.21))
        # shift drag start to top right quadrant. check both y-maj and x-maj.
        self.simulate_drag((1210,1210), (1230,310), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (1.29, 0.31))
        self.simulate_drag((1290,310), (1110,420), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].end, (1.18, 0.42))

    def test_nudge_line(self):
        # add line (0.2, 0.2), (0.8, 0.8)
        self.document_controller.add_line_region()
        # select it
        self.image_panel.display.graphic_selection.set(0)
        # move it left
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.200, 0.199))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.200, 0.189))
        # move it up
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.199, 0.189))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.189, 0.189))
        # move it right
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.189, 0.190))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.189, 0.200))
        # move it down
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.190, 0.200))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].start, (0.200, 0.200))

    def test_nudge_rect(self):
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_rectangle_region()
        # select it
        self.image_panel.display.graphic_selection.set(0)
        # move it left
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.250, 0.249))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.250, 0.239))
        # move it up
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.249, 0.239))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.239, 0.239))
        # move it right
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.239, 0.240))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.239, 0.250))
        # move it down
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.240, 0.250))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.250, 0.250))

    def test_nudge_ellipse(self):
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_ellipse_region()
        # select it
        self.image_panel.display.graphic_selection.set(0)
        # move it left
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.250, 0.249))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.250, 0.239))
        # move it up
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.249, 0.239))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("up", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.239, 0.239))
        # move it right
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.239, 0.240))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("right", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.239, 0.250))
        # move it down
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down"))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.240, 0.250))
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("down", self.app.ui.create_modifiers_by_id_list(["shift"])))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.250, 0.250))

    def test_drag_point_moves_the_point_graphic(self):
        # add point (0.5, 0.5)
        self.document_controller.add_point_region()
        # make sure items it is in the right place
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].position, (0.5, 0.5))
        # select it
        self.image_panel.display.graphic_selection.set(0)
        self.simulate_drag((500,500), (300,400))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].position, (0.3, 0.4))

    def test_click_on_point_selects_it(self):
        # add point (0.5, 0.5)
        self.document_controller.add_point_region()
        # make sure items it is in the right place
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].position, (0.5, 0.5))
        # select it
        self.simulate_click((100,100))
        self.assertFalse(self.image_panel.display.graphic_selection.indexes)
        self.simulate_click((500,500))
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.image_panel.display.graphic_selection.indexes)

    # this helps test out cursor positioning
    def test_map_widget_to_image(self):
        # assumes the test widget is 640x480
        self.image_panel.display_canvas_item.update_layout((0, 0), (480, 640))
        self.assertIsNotNone(self.image_panel.display_canvas_item.map_widget_to_image((240, 320)))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_widget_to_image((240, 320)), (500.0, 500.0))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_widget_to_image((0, 80)), (0.0, 0.0))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_widget_to_image((480, 560)), (1000.0, 1000.0))

    # this helps test out cursor positioning
    def test_map_widget_to_offset_image(self):
        # assumes the test widget is 640x480
        self.image_panel.display_canvas_item.update_layout((0, 0), (480, 640))
        self.image_panel.display_canvas_item.move_left()  # 10 pixels left
        self.image_panel.display_canvas_item.move_left()  # 10 pixels left
        self.assertIsNotNone(self.image_panel.display_canvas_item.map_widget_to_image((240, 320)))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_widget_to_image((240, 300)), (500.0, 500.0))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_widget_to_image((0, 60)), (0.0, 0.0))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_widget_to_image((480, 540)), (1000.0, 1000.0))

    def test_resize_rectangle(self):
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_rectangle_region()
        # make sure items it is in the right place
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[1], (0.5, 0.5))
        # select it
        self.image_panel.display.graphic_selection.set(0)
        # drag top left corner
        self.simulate_drag((250,250), (300,250))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.30, 0.25))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[1], (0.45, 0.5))
        # drag with shift key
        self.simulate_drag((300,250), (350,250), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.35, 0.35))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[1], (0.4, 0.4))

    def test_resize_nonsquare_rectangle(self):
        self.image_panel.display_canvas_item.update_layout((0, 0), (2000, 1000))
        self.data_item = self.document_model.set_data_by_key("test", numpy.zeros((2000, 1000)))
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_rectangle_region()
        # make sure items it is in the right place
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[1], (0.5, 0.5))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[0]), (500, 250))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[1]), (1000, 500))
        # select it
        self.image_panel.display.graphic_selection.set(0)
        # drag top left corner
        self.simulate_drag((500,250), (800,250))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[0]), (800, 250))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[1]), (700, 500))
        # drag with shift key
        self.simulate_drag((800,250), (900,250), Test.KeyboardModifiers(shift=True))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[0]), (1000, 250))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[1]), (500, 500))

    def test_resize_nonsquare_ellipse(self):
        self.image_panel.display_canvas_item.update_layout((0, 0), (2000, 1000))
        self.data_item = self.document_model.set_data_by_key("test", numpy.zeros((2000, 1000)))
        # add rect (0.25, 0.25), (0.5, 0.5)
        self.document_controller.add_ellipse_region()
        # make sure items it is in the right place
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[0], (0.25, 0.25))
        self.assertClosePoint(self.data_item.displays[0].drawn_graphics[0].bounds[1], (0.5, 0.5))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[0]), (500, 250))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[1]), (1000, 500))
        # select it
        self.image_panel.display.graphic_selection.set(0)
        # drag top left corner
        self.simulate_drag((500,250), (800,250), Test.KeyboardModifiers(alt=True))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[0]), (800, 250))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[1]), (400, 500))
        # drag with shift key
        self.simulate_drag((800,250), (900,250), Test.KeyboardModifiers(shift=True, alt=True))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[0]), (900, 400))
        self.assertClosePoint(self.image_panel.display_canvas_item.map_image_norm_to_image(self.data_item.displays[0].drawn_graphics[0].bounds[1]), (200, 200))

    def test_insert_remove_graphics_and_selection(self):
        self.assertFalse(self.image_panel.display.graphic_selection.indexes)
        self.document_controller.add_rectangle_region()
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.image_panel.display.graphic_selection.indexes)
        graphic = Graphics.RectangleGraphic()
        graphic.bounds = ((0.5,0.5), (0.25,0.25))
        self.data_item.displays[0].insert_graphic(0, graphic)
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(1 in self.image_panel.display.graphic_selection.indexes)
        self.data_item.displays[0].remove_graphic(self.data_item.displays[0].drawn_graphics[0])
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.image_panel.display.graphic_selection.indexes)

    def test_delete_key_when_graphic_selected_removes_the_graphic(self):
        self.document_controller.add_rectangle_region()
        modifiers = Test.KeyboardModifiers()
        # check assumptions
        self.assertEqual(len(self.data_item.displays[0].drawn_graphics), 1)
        self.assertEqual(len(self.image_panel.display.graphic_selection.indexes), 1)
        # do focusing click, then delete
        self.image_panel.canvas_item.root_container.canvas_widget.on_mouse_clicked(100, 100, modifiers)
        self.image_panel.canvas_item.root_container.canvas_widget.on_key_pressed(Test.Key(None, "delete", modifiers))
        # check results
        self.assertEqual(len(self.data_item.displays[0].drawn_graphics), 0)

    def test_delete_key_when_nothing_selected_removes_the_image_panel_content(self):
        modifiers = Test.KeyboardModifiers()
        # check assumptions
        self.assertIsNotNone(self.image_panel.get_displayed_data_item())
        # do focusing click, then delete
        self.image_panel.canvas_item.root_container.canvas_widget.on_mouse_clicked(100, 100, modifiers)
        self.image_panel.canvas_item.root_container.canvas_widget.on_key_pressed(Test.Key(None, "delete", modifiers))
        # check results
        self.assertIsNone(self.image_panel.get_displayed_data_item())

    def setup_line_plot(self, canvas_shape=None):
        canvas_shape = canvas_shape if canvas_shape else (480, 640)  # yes I know these are backwards
        data_item_1d = self.document_model.set_data_by_key("test_1d", create_1d_data())
        self.image_panel.set_displayed_data_item(data_item_1d)
        self.image_panel.display_canvas_item.update_layout((0, 0), canvas_shape)
        self.image_panel_drawing_context = self.app.ui.create_offscreen_drawing_context()
        # trigger layout
        self.image_panel.display_canvas_item.wait_for_prepare_data()  # force prepare_display_on_thread to finish before _repaint
        self.document_controller.periodic()
        self.image_panel.display_canvas_item.line_graph_canvas_item._repaint(self.image_panel_drawing_context)
        return self.image_panel.display_canvas_item

    def test_line_plot_initially_displays_entire_data_in_horizontal_direction(self):
        line_plot_canvas_item = self.setup_line_plot()
        self.assertEqual(line_plot_canvas_item.line_graph_canvas_item.data_info.drawn_left_channel, 0)
        self.assertEqual(line_plot_canvas_item.line_graph_canvas_item.data_info.drawn_right_channel, 1024)

    def test_line_plot_initially_displays_entire_data_in_vertical_direction(self):
        line_plot_canvas_item = self.setup_line_plot()
        self.assertEqual(line_plot_canvas_item.line_graph_canvas_item.data_info.drawn_data_min, 0.0)
        self.assertEqual(line_plot_canvas_item.line_graph_canvas_item.data_info.drawn_data_max, 1.0)

    def test_mouse_tracking_moves_horizontal_scale(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        modifiers = Test.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_horizontal(Geometry.IntPoint(x=320, y=465), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=360, y=465), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        offset = -1024.0 * 40.0 / plot_width
        self.assertEqual(self.image_panel.display.left_channel, int(offset))
        self.assertEqual(self.image_panel.display.right_channel, int(1024 + offset))

    def test_mouse_tracking_moves_vertical_scale(self):
        line_plot_canvas_item = self.setup_line_plot()
        # notice: dragging increasing y drags down.
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        modifiers = Test.KeyboardModifiers()
        line_plot_canvas_item.begin_tracking_vertical(Geometry.IntPoint(x=30, y=270), rescale=False)
        line_plot_canvas_item.continue_tracking(Geometry.IntPoint(x=30, y=240), modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        offset = -1.0 * 30.0 / plot_height
        self.assertAlmostEqual(self.image_panel.display.y_min, 0.0 + offset)
        self.assertAlmostEqual(self.image_panel.display.y_max, 1.0 + offset)

    def test_mouse_tracking_shrink_scale_by_10_around_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=-96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        self.assertEqual(self.image_panel.display.left_channel, int(round(512 - int(plot_width * 0.5) * 10 * channel_per_pixel)))
        self.assertEqual(self.image_panel.display.right_channel, int(round(512 + int(plot_width * 0.5) * 10 * channel_per_pixel)))

    def test_mouse_tracking_expand_scale_by_10_around_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + plot_width*0.5, y=465)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        # self.__display.left_channel = int(round(self.__tracking_start_channel - new_drawn_channel_per_pixel * self.__tracking_start_origin_pixel))
        self.assertEqual(self.image_panel.display.left_channel, int(round(512 - int(plot_width * 0.5) * 0.1 * channel_per_pixel)))
        self.assertEqual(self.image_panel.display.right_channel, int(round(512 + int(plot_width * 0.5) * 0.1 * channel_per_pixel)))

    def test_mouse_tracking_shrink_scale_by_10_around_non_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + 200, y=465)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=-96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        self.assertEqual(self.image_panel.display.left_channel, int(round(200 * channel_per_pixel - 200 * 10 * channel_per_pixel)))
        self.assertEqual(self.image_panel.display.right_channel, int(round(200 * channel_per_pixel + (plot_width - 200) * 10 * channel_per_pixel)))

    def test_mouse_tracking_expand_scale_by_10_around_non_center(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        pos = Geometry.IntPoint(x=plot_left + 400, y=465)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=96, height=0)
        line_plot_canvas_item.begin_tracking_horizontal(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        channel_per_pixel = 1024.0 / plot_width
        self.assertEqual(self.image_panel.display.left_channel, int(round(400 * channel_per_pixel - 400 * 0.1 * channel_per_pixel)))
        self.assertEqual(self.image_panel.display.right_channel, int(round(400 * channel_per_pixel + (plot_width - 400) * 0.1 * channel_per_pixel)))

    def test_mouse_tracking_vertical_shrink_with_origin_at_bottom(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        pos = Geometry.IntPoint(x=30, y=plot_bottom - 200)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=40)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        scaling = float(plot_bottom - pos.y) / float(plot_bottom - (pos.y + offset.height))
        self.assertAlmostEqual(self.image_panel.display.y_min, 0.0)
        self.assertAlmostEqual(self.image_panel.display.y_max, scaling)

    def test_mouse_tracking_vertical_shrink_with_origin_in_middle(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.image_panel.display.y_min = -0.5
        self.image_panel.display.y_max = 0.5
        self.image_panel.display_canvas_item.prepare_display_on_thread()
        self.document_controller.periodic()
        self.image_panel.display_canvas_item.line_graph_canvas_item._repaint(self.image_panel_drawing_context)
        # now stretch 1/2 + 100 to 1/2 + 150
        pos = Geometry.IntPoint(x=30, y=plot_bottom-320)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=50)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height/2.0) - pos.y
        scaling = float(relative_y) / float(relative_y - offset.height)
        self.assertAlmostEqual(self.image_panel.display.y_min, -0.5 * scaling)
        self.assertAlmostEqual(self.image_panel.display.y_max, 0.5 * scaling)

    def test_mouse_tracking_vertical_shrink_with_origin_at_200(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.image_panel.display.y_min = -0.2
        self.image_panel.display.y_max = 0.8
        self.image_panel.display_canvas_item.prepare_display_on_thread()
        self.document_controller.periodic()
        self.image_panel.display_canvas_item.line_graph_canvas_item._repaint(self.image_panel_drawing_context)
        # now stretch 1/2 + 100 to 1/2 + 150
        pos = Geometry.IntPoint(x=30, y=plot_bottom-320)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=50)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height*0.2) - pos.y
        scaling = float(relative_y) / float(relative_y - offset.height)
        self.assertAlmostEqual(self.image_panel.display.y_min, -0.2 * scaling)
        self.assertAlmostEqual(self.image_panel.display.y_max, 0.8 * scaling)

    def test_mouse_tracking_vertical_shrink_with_calibrated_origin_at_200(self):
        logging.getLogger().setLevel(logging.DEBUG)
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        data_item = self.image_panel.display.data_item
        # adjust image panel display and trigger layout
        intensity_calibration = data_item.intensity_calibration
        intensity_calibration.offset = -0.2
        data_item.set_intensity_calibration(intensity_calibration)
        self.image_panel.display_canvas_item.wait_for_prepare_data()  # force prepare_display_on_thread to finish before _repaint
        self.document_controller.periodic()
        # now stretch 1/2 + 100 to 1/2 + 150
        pos = Geometry.IntPoint(x=30, y=plot_bottom-320)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=50)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height*0.2) - pos.y
        scaling = float(relative_y) / float(relative_y - offset.height)
        self.assertAlmostEqual(self.image_panel.display.y_min, -0.2 * scaling + 0.2)
        self.assertAlmostEqual(self.image_panel.display.y_max, 0.8 * scaling + 0.2)

    def test_mouse_tracking_vertical_drag_down_does_not_go_negative(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.image_panel.display.y_min = -0.5
        self.image_panel.display.y_max = 0.5
        self.image_panel.display_canvas_item.prepare_display_on_thread()
        self.document_controller.periodic()
        self.image_panel.display_canvas_item.line_graph_canvas_item._repaint(self.image_panel_drawing_context)
        # now stretch way past top
        pos = Geometry.IntPoint(x=30, y=20)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=plot_height)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height/2.0) - pos.y
        scaling = plot_height
        new_drawn_data_per_pixel = 1.0/plot_height * (plot_bottom - plot_height*0.5 - pos.y)
        self.assertAlmostEqual(self.image_panel.display.y_min, -new_drawn_data_per_pixel * plot_height*0.5)
        self.assertAlmostEqual(self.image_panel.display.y_max, new_drawn_data_per_pixel * plot_height*0.5)

    def test_mouse_tracking_vertical_drag_up_does_not_go_negative(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_height = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.height - 1
        plot_bottom = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.bottom - 1 + plot_origin.y
        # adjust image panel display and trigger layout
        self.image_panel.display.y_min = -0.5
        self.image_panel.display.y_max = 0.5
        self.image_panel.display_canvas_item.prepare_display_on_thread()
        self.document_controller.periodic()
        self.image_panel.display_canvas_item.line_graph_canvas_item._repaint(self.image_panel_drawing_context)
        # now stretch way past top
        pos = Geometry.IntPoint(x=30, y=plot_height-20)
        modifiers = Test.KeyboardModifiers()
        offset = Geometry.IntSize(width=0, height=-plot_height)
        line_plot_canvas_item.begin_tracking_vertical(pos, rescale=True)
        line_plot_canvas_item.continue_tracking(pos + offset, modifiers)
        line_plot_canvas_item.end_tracking(modifiers)
        relative_y = (plot_bottom - plot_height/2.0) - pos.y
        scaling = plot_height
        new_drawn_data_per_pixel = -1.0/plot_height * (plot_bottom - plot_height*0.5 - pos.y)
        self.assertAlmostEqual(self.image_panel.display.y_min, -new_drawn_data_per_pixel * plot_height*0.5)
        self.assertAlmostEqual(self.image_panel.display.y_max, new_drawn_data_per_pixel * plot_height*0.5)

    def test_combined_horizontal_drag_and_expand_works_nominally(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        v = line_plot_canvas_item.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)[0] + 8
        line_plot_canvas_item.mouse_pressed(plot_left, v, Test.KeyboardModifiers(control=True))
        line_plot_canvas_item.mouse_position_changed(plot_left+96, v, Test.KeyboardModifiers(control=True))
        # trigger layout. necessary so that drawn values get updated. bad architecture!
        self.image_panel.display_canvas_item.prepare_display_on_thread()
        self.document_controller.periodic()
        self.image_panel.display_canvas_item.line_graph_canvas_item._repaint(self.image_panel_drawing_context)
        # continue
        line_plot_canvas_item.mouse_position_changed(plot_left+96, v, Test.KeyboardModifiers())
        line_plot_canvas_item.mouse_position_changed(plot_left+196, v, Test.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+116, 190, Test.KeyboardModifiers())
        channel_per_pixel = 1024.0/10 / plot_width
        self.assertEqual(self.image_panel.display.left_channel, int(0 - channel_per_pixel * 100))
        self.assertEqual(self.image_panel.display.right_channel, int(int(1024/10.0) - channel_per_pixel * 100))

    def test_click_on_selection_makes_it_selected(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        region = Region.IntervalRegion()
        region.start = 0.3
        region.end = 0.4
        line_plot_data_item.add_region(region)
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_data_item.displays[0].graphic_selection.indexes), 0)
        # do the click
        line_plot_canvas_item.mouse_pressed(plot_left+plot_width * 0.35, 100, Test.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+plot_width * 0.35, 100, Test.KeyboardModifiers())
        # make sure results are correct
        self.assertEqual(len(line_plot_data_item.displays[0].graphic_selection.indexes), 1)

    def test_click_outside_selection_makes_it_unselected(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        region = Region.IntervalRegion()
        region.start = 0.3
        region.end = 0.4
        line_plot_data_item.add_region(region)
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_data_item.displays[0].graphic_selection.indexes), 0)
        # do the first click to select
        line_plot_canvas_item.mouse_pressed(plot_left+plot_width * 0.35, 100, Test.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+plot_width * 0.35, 100, Test.KeyboardModifiers())
        # make sure results are correct
        self.assertEqual(len(line_plot_data_item.displays[0].graphic_selection.indexes), 1)
        # do the second click to deselect
        line_plot_canvas_item.mouse_pressed(plot_left+plot_width * 0.1, 100, Test.KeyboardModifiers())
        line_plot_canvas_item.mouse_released(plot_left+plot_width * 0.1, 100, Test.KeyboardModifiers())
        # make sure results are correct
        self.assertEqual(len(line_plot_data_item.displays[0].graphic_selection.indexes), 0)

    def test_click_drag_interval_end_channel_to_right_adjust_end_channel(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        region = Region.IntervalRegion()
        region.start = 0.3
        region.end = 0.4
        line_plot_data_item.add_region(region)
        # select, then click drag
        modifiers = Test.KeyboardModifiers()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.4, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.5, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.5, 100, modifiers)
        # make sure results are correct
        self.assertAlmostEqual(line_plot_data_item.regions[0].start, 0.3)
        self.assertAlmostEqual(line_plot_data_item.regions[0].end, 0.5)

    def test_click_drag_interval_end_channel_to_left_of_start_channel_results_in_left_less_than_right(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        region = Region.IntervalRegion()
        region.start = 0.3
        region.end = 0.4
        line_plot_data_item.add_region(region)
        # select, then click drag
        modifiers = Test.KeyboardModifiers()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.4, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.2, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.2, 100, modifiers)
        # make sure results are correct
        self.assertAlmostEqual(line_plot_data_item.regions[0].start, 0.2, 2)  # pixel accuracy, approx. 1/500
        self.assertAlmostEqual(line_plot_data_item.regions[0].end, 0.3, 2)  # pixel accuracy, approx. 1/500

    def test_click_drag_interval_tool_creates_selection(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        self.document_controller.tool_mode = "interval"
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_data_item.regions), 0)
        # click drag
        modifiers = Test.KeyboardModifiers()
        line_plot_canvas_item.mouse_pressed(plot_left + plot_width * 0.35, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.40, 100, modifiers)
        line_plot_canvas_item.mouse_position_changed(plot_left + plot_width * 0.50, 100, modifiers)
        line_plot_canvas_item.mouse_released(plot_left + plot_width * 0.50, 100, modifiers)
        # make sure results are correct
        self.assertEqual(len(line_plot_data_item.regions), 1)
        self.assertTrue(isinstance(line_plot_data_item.regions[0], Region.IntervalRegion))
        self.assertAlmostEqual(line_plot_data_item.regions[0].start, 0.35, 2)  # pixel accuracy, approx. 1/500
        self.assertAlmostEqual(line_plot_data_item.regions[0].end, 0.50, 2)  # pixel accuracy, approx. 1/500
        # and that tool is returned to pointer
        self.assertEqual(self.document_controller.tool_mode, "pointer")

    def test_delete_line_profile_with_key(self):
        line_plot_canvas_item = self.setup_line_plot()
        plot_origin = line_plot_canvas_item.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), line_plot_canvas_item)
        plot_left = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = line_plot_canvas_item.line_graph_canvas_item.canvas_rect.width
        line_plot_data_item = self.document_model.data_items[1]
        region = Region.IntervalRegion()
        region.start = 0.3
        region.end = 0.4
        line_plot_data_item.add_region(region)
        line_plot_data_item.displays[0].graphic_selection.set(0)
        # make sure assumptions are correct
        self.assertEqual(len(line_plot_data_item.regions), 1)
        self.assertEqual(len(line_plot_data_item.displays[0].graphic_selection.indexes), 1)
        # hit the delete key
        self.image_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("delete"))
        self.assertEqual(len(line_plot_data_item.regions), 0)

    def test_key_gets_dispatched_to_image_canvas_item(self):
        modifiers = Test.KeyboardModifiers()
        self.image_panel.canvas_item.root_container.canvas_widget.on_mouse_clicked(100, 100, modifiers)
        self.image_panel.canvas_item.root_container.canvas_widget.on_key_pressed(Test.Key(None, "up", modifiers))
        # self.image_panel.display_canvas_item.key_pressed(Test.Key(None, "up", modifiers))  # direct dispatch, should work
        self.assertEqual(self.image_panel.display_canvas_item.scroll_area_canvas_item.content.canvas_rect, ((-10, 0), (1000, 1000)))

    def test_drop_on_overlay_middle_triggers_replace_data_item_in_panel_action(self):
        width, height = 640, 480
        image_panel = TestImagePanel()
        overlay = ImagePanel.ImagePanelOverlayCanvasItem(image_panel)
        overlay.update_layout((0, 0), (height, width))
        mime_data = None
        overlay.drag_enter(mime_data)
        overlay.drag_move(mime_data, int(width*0.5), int(height*0.5))
        overlay.drop(mime_data, int(width*0.5), int(height*0.5))
        self.assertEqual(image_panel.drop_region, "middle")

    def test_drop_on_overlay_edge_triggers_split_image_panel_action(self):
        width, height = 640, 480
        image_panel = TestImagePanel()
        overlay = ImagePanel.ImagePanelOverlayCanvasItem(image_panel)
        overlay.update_layout((0, 0), (height, width))
        mime_data = None
        overlay.drag_enter(mime_data)
        overlay.drag_move(mime_data, int(width*0.05), int(height*0.5))
        overlay.drop(mime_data, int(width*0.05), int(height*0.5))
        self.assertEqual(image_panel.drop_region, "left")


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
