# standard libraries
import contextlib
import copy
import logging
import math
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics

class TestRegionClass(unittest.TestCase):

    def test_changing_point_region_updates_drawn_graphic(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_region = Graphics.PointGraphic()
            display_specifier.display.add_graphic(point_region)
            drawn_graphic = display_specifier.display.graphics[0]
            self.assertEqual(point_region.position, drawn_graphic.position)
            point_region.position = (0.3, 0.7)
            self.assertEqual(point_region.position, drawn_graphic.position)

    def test_changing_drawn_graphic_updates_point_region(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_region = Graphics.PointGraphic()
            display_specifier.display.add_graphic(point_region)
            drawn_graphic = display_specifier.display.graphics[0]
            self.assertEqual(point_region.position, drawn_graphic.position)
            drawn_graphic.position = (0.3, 0.7)
            self.assertEqual(point_region.position, drawn_graphic.position)

    def test_changing_region_properties_change_drawn_graphic_properties(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            regions = list()
            regions.append(Graphics.PointGraphic())
            regions.append(Graphics.RectangleGraphic())
            regions.append(Graphics.EllipseGraphic())
            regions.append(Graphics.LineGraphic())
            regions.append(Graphics.IntervalGraphic())
            regions.append(Graphics.ChannelGraphic())
            for region in regions:
                region.label = "label"
                region.is_position_locked = False
                region.is_shape_locked = False
                region.is_bounds_constrained = False
                display_specifier.display.add_graphic(region)
                drawn_graphic = display_specifier.display.graphics[-1]
                self.assertEqual(region.label, drawn_graphic.label)
                self.assertEqual(region.is_position_locked, drawn_graphic.is_position_locked)
                self.assertEqual(region.is_shape_locked, drawn_graphic.is_shape_locked)
                self.assertEqual(region.is_bounds_constrained, drawn_graphic.is_bounds_constrained)
                region.label = "label2"
                region.is_position_locked = True
                region.is_shape_locked = True
                region.is_bounds_constrained = True
                self.assertEqual(region.label, drawn_graphic.label)
                self.assertEqual(region.is_position_locked, drawn_graphic.is_position_locked)
                self.assertEqual(region.is_shape_locked, drawn_graphic.is_shape_locked)
                self.assertEqual(region.is_bounds_constrained, drawn_graphic.is_bounds_constrained)

    def test_copying_region_with_empty_label_copies_it_correctly(self):
        region = Graphics.PointGraphic()
        region_copy = copy.deepcopy(region)
        self.assertIsNone(region.label)
        self.assertIsNone(region_copy.label)

    def test_removing_region_from_data_source_closes_it(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_region = Graphics.PointGraphic()
            display_specifier.display.add_graphic(point_region)
            self.assertFalse(point_region._closed)
            display_specifier.display.remove_graphic(point_region)
            self.assertTrue(point_region._closed)

    def test_removing_data_item_closes_point_region(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_region = Graphics.PointGraphic()
            display_specifier.display.add_graphic(point_region)
            self.assertFalse(point_region._closed)
            document_model.remove_data_item(data_item)
            self.assertTrue(point_region._closed)

    def test_region_mask_with_different_types_of_graphics(self):
        line_graphic = Graphics.LineGraphic()
        line_graphic.start = (0.25, 0.25)
        line_graphic.end = (0.75, 0.75)
        spot_graphic = Graphics.SpotGraphic()
        spot_graphic.bounds = (0.2, 0.2), (0.1, 0.1)
        ellipse_graphic = Graphics.EllipseGraphic()
        ellipse_graphic.bounds = (0.2, 0.2), (0.1, 0.1)
        rect_graphic = Graphics.RectangleGraphic()
        rect_graphic.bounds = (0.25, 0.25), (0.5, 0.5)
        point_graphic = Graphics.PointGraphic()
        point_graphic.position = (0.25, 0.25)
        wedge_graphic = Graphics.WedgeGraphic()
        line_graphic.get_mask((256, 256))
        spot_graphic.get_mask((256, 256))
        ellipse_graphic.get_mask((256, 256))
        rect_graphic.get_mask((256, 256))
        point_graphic.get_mask((256, 256))

    def test_region_mask_ellipse(self):
        ellipse_graphic = Graphics.EllipseGraphic()
        ellipse_graphic.bounds = (0.2, 0.2), (0.1, 0.1)
        mask = ellipse_graphic.get_mask((1000, 1000))
        self.assertEqual(mask.data[200, 200], 0)  # top left
        self.assertEqual(mask.data[200, 300], 0)  # bottom left
        self.assertEqual(mask.data[300, 300], 0)  # bottom right
        self.assertEqual(mask.data[300, 200], 0)  # bottom left
        self.assertEqual(mask.data[250, 200], 1)  # center top
        self.assertEqual(mask.data[300, 250], 1)  # center right
        self.assertEqual(mask.data[250, 300], 1)  # center bottom
        self.assertEqual(mask.data[200, 250], 1)  # center left

    def test_region_mask_spot(self):
        spot_graphic = Graphics.SpotGraphic()
        spot_graphic.bounds = (0.2, 0.2), (0.1, 0.1)
        mask = spot_graphic.get_mask((1000, 1000))
        self.assertEqual(mask.data[200, 200], 0)  # top left
        self.assertEqual(mask.data[200, 300], 0)  # bottom left
        self.assertEqual(mask.data[300, 300], 0)  # bottom right
        self.assertEqual(mask.data[300, 200], 0)  # bottom left
        self.assertEqual(mask.data[250, 200], 1)  # center top
        self.assertEqual(mask.data[300, 250], 1)  # center right
        self.assertEqual(mask.data[250, 300], 1)  # center bottom
        self.assertEqual(mask.data[200, 250], 1)  # center left

        self.assertEqual(mask.data[800, 800], 0)  # top left
        self.assertEqual(mask.data[800, 700], 0)  # bottom left
        self.assertEqual(mask.data[700, 700], 0)  # bottom right
        self.assertEqual(mask.data[700, 800], 0)  # bottom left
        self.assertEqual(mask.data[750, 800], 1)  # center top
        self.assertEqual(mask.data[700, 750], 1)  # center right
        self.assertEqual(mask.data[750, 700], 1)  # center bottom
        self.assertEqual(mask.data[800, 750], 1)  # center left

    def test_region_mask_rect(self):
        rect_graphic = Graphics.RectangleGraphic()
        rect_graphic.bounds = (0.2, 0.2), (0.1, 0.1)
        mask = rect_graphic.get_mask((1000, 1000))
        self.assertEqual(mask.data[200, 200], 1)  # top left
        self.assertEqual(mask.data[200, 300], 1)  # bottom left
        self.assertEqual(mask.data[300, 300], 1)  # bottom right
        self.assertEqual(mask.data[300, 200], 1)  # bottom left
        self.assertEqual(mask.data[250, 200], 1)  # center top
        self.assertEqual(mask.data[300, 250], 1)  # center right
        self.assertEqual(mask.data[250, 300], 1)  # center bottom
        self.assertEqual(mask.data[200, 250], 1)  # center left

    def test_region_mask_wedge(self):
        rect_graphic = Graphics.WedgeGraphic()
        rect_graphic.angle_interval = -math.pi / 2, 0
        mask = rect_graphic.get_mask((1000, 1000))
        self.assertTrue(mask.data[600, 600])  # bottom right
        self.assertFalse(mask.data[600, 400])  # top right
        self.assertTrue(mask.data[400, 400])  # top left
        self.assertFalse(mask.data[400, 600])  # bottom left

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
