# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DataItem
from nion.swift import DocumentController
from nion.swift import Graphics
from nion.swift import ImagePanel
from nion.swift import Storage
from nion.swift import Test


class TestGraphicSelectionClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_selection_set(self):
        selection = ImagePanel.GraphicSelection()
        selection.set(0)
        selection.set(1)
        self.assertEqual(len(selection.indexes), 1)


class TestImagePanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), catch_stdout=False, set_global=False)
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        self.document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        self.document_controller.create_default_data_groups()
        default_data_group = self.document_controller.data_groups[0]
        self.image_panel = self.document_controller.selected_image_panel
        self.data_item = self.document_controller.set_data_by_key("test", numpy.zeros((1000, 1000)))
        self.image_panel.data_panel_selection = DataItem.DataItemSpecifier(default_data_group, self.data_item)

    def tearDown(self):
        self.image_panel.close()
        self.document_controller.close()

    def simulate_click(self, p, modifiers=None):
        modifiers = Test.KeyboardModifiers() if not modifiers else modifiers
        self.image_panel.mouse_pressed(p, modifiers)
        self.image_panel.mouse_released(p, modifiers)

    def simulate_drag(self, p1, p2, modifiers=None):
        modifiers = Test.KeyboardModifiers() if not modifiers else modifiers
        self.image_panel.mouse_pressed(p1, modifiers)
        self.image_panel.mouse_position_changed(p1, modifiers)
        self.image_panel.mouse_position_changed(Graphics.midpoint(p1, p2), modifiers)
        self.image_panel.mouse_position_changed(p2, modifiers)
        self.image_panel.mouse_released(p2, modifiers)

    # user deletes data item that is displayed. make sure we remove the display.
    def test_disappearing_data(self):
        self.assertEqual(self.image_panel.data_panel_selection.data_group, self.document_controller.data_groups[0])
        self.assertEqual(self.image_panel.data_panel_selection.data_item, self.document_controller.data_groups[0].data_items[0])
        self.document_controller.processing_invert()
        data_group = self.document_controller.data_groups[0]
        data_item_container = data_group.data_items[0]
        data_item = data_item_container.data_items[0]
        self.assertEqual(self.image_panel.data_panel_selection.data_group, data_group)
        self.assertEqual(self.image_panel.data_panel_selection.data_item_container, data_item_container)
        self.assertEqual(self.image_panel.data_panel_selection.data_item, data_item)
        data_item_container.data_items.remove(data_item)
        self.assertEqual(self.image_panel.data_panel_selection.data_group, data_group)
        self.assertIsNone(self.image_panel.data_panel_selection.data_item_container)
        self.assertIsNone(self.image_panel.data_panel_selection.data_item)

    def test_select_multiple(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_graphic()
        self.document_controller.add_ellipse_graphic()
        # click outside so nothing is selected
        self.simulate_click((0, 0))
        self.assertEqual(len(self.image_panel.graphic_selection.indexes), 0)
        # select the ellipse
        self.simulate_click((725, 500))
        self.assertEqual(len(self.image_panel.graphic_selection.indexes), 1)
        self.assertTrue(1 in self.image_panel.graphic_selection.indexes)
        # select the line
        self.simulate_click((200, 200))
        self.assertEqual(len(self.image_panel.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.image_panel.graphic_selection.indexes)
        # add the ellipse to the selection. click inside the right side.
        self.simulate_click((725, 500), Test.KeyboardModifiers(shift=True))
        self.assertEqual(len(self.image_panel.graphic_selection.indexes), 2)
        self.assertTrue(0 in self.image_panel.graphic_selection.indexes)
        # remove the ellipse from the selection. click inside the right side.
        self.simulate_click((725, 500), Test.KeyboardModifiers(shift=True))
        self.assertEqual(len(self.image_panel.graphic_selection.indexes), 1)
        self.assertTrue(0 in self.image_panel.graphic_selection.indexes)

    def assertClosePoint(self, p1, p2, e=0.00001):
        self.assertTrue(Graphics.distance(p1, p2) < e)

    def assertCloseRectangle(self, r1, r2, e=0.00001):
        self.assertTrue(Graphics.distance(r1[0], r2[0]) < e and Graphics.distance(r1[1], r2[1]) < e)

    def test_drag_multiple(self):
        # add line (0.2, 0.2), (0.8, 0.8) and ellipse ((0.25, 0.25), (0.5, 0.5)).
        self.document_controller.add_line_graphic()
        self.document_controller.add_ellipse_graphic()
        # make sure items are in the right place
        self.assertClosePoint(self.data_item.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.data_item.graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.data_item.graphics[1].bounds, ((0.25, 0.25), (0.5, 0.5)))
        # select both
        self.image_panel.graphic_selection.set(0)
        self.image_panel.graphic_selection.add(1)
        self.assertEqual(len(self.image_panel.graphic_selection.indexes), 2)
        # drag by (0.1, 0.2)
        self.simulate_drag((500,500), (600,700))
        self.assertCloseRectangle(self.data_item.graphics[1].bounds, ((0.35, 0.45), (0.5, 0.5)))
        self.assertClosePoint(self.data_item.graphics[0].start, (0.3, 0.4))
        self.assertClosePoint(self.data_item.graphics[0].end, (0.9, 1.0))
        # drag on endpoint (0.3, 0.4) make sure it drags all
        self.simulate_drag((300,400), (200,200))
        self.assertClosePoint(self.data_item.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.data_item.graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.data_item.graphics[1].bounds, ((0.25, 0.25), (0.5, 0.5)))
        # now select just the line, drag middle of circle. should only drag circle.
        self.image_panel.graphic_selection.set(0)
        self.simulate_drag((700,500), (800,500))
        self.assertClosePoint(self.data_item.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.data_item.graphics[0].end, (0.8, 0.8))
        self.assertCloseRectangle(self.data_item.graphics[1].bounds, ((0.35, 0.25), (0.5, 0.5)))

    def test_drag_line_part(self):
        # add line (0.2, 0.2), (0.8, 0.8)
        self.document_controller.add_line_graphic()
        # make sure items it is in the right place
        self.assertClosePoint(self.data_item.graphics[0].start, (0.2, 0.2))
        self.assertClosePoint(self.data_item.graphics[0].end, (0.8, 0.8))
        # select it
        self.image_panel.graphic_selection.set(0)
        self.simulate_drag((200,200), (300,400))
        self.assertClosePoint(self.data_item.graphics[0].start, (0.3, 0.4))
        self.assertClosePoint(self.data_item.graphics[0].end, (0.8, 0.8))
