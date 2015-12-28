# futures
from __future__ import absolute_import

# standard libraries
import contextlib
import copy
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Region


class TestRegionClass(unittest.TestCase):

    def test_changing_point_region_updates_drawn_graphic(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_region = Region.PointRegion()
            display_specifier.buffered_data_source.add_region(point_region)
            drawn_graphic = display_specifier.display.drawn_graphics[0]
            self.assertEqual(point_region.position, drawn_graphic.position)
            point_region.position = (0.3, 0.7)
            self.assertEqual(point_region.position, drawn_graphic.position)

    def test_changing_drawn_graphic_updates_point_region(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_region = Region.PointRegion()
            display_specifier.buffered_data_source.add_region(point_region)
            drawn_graphic = display_specifier.display.drawn_graphics[0]
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
            regions.append(Region.PointRegion())
            regions.append(Region.RectRegion())
            regions.append(Region.EllipseRegion())
            regions.append(Region.LineRegion())
            regions.append(Region.IntervalRegion())
            for region in regions:
                region.label = "label"
                region.is_position_locked = False
                region.is_shape_locked = False
                region.is_bounds_constrained = False
                display_specifier.buffered_data_source.add_region(region)
                drawn_graphic = display_specifier.display.drawn_graphics[-1]
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
        region = Region.PointRegion()
        region_copy = copy.deepcopy(region)
        self.assertIsNone(region.label)
        self.assertIsNone(region_copy.label)

    def test_removing_region_from_data_source_closes_it(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_region = Region.PointRegion()
            display_specifier.buffered_data_source.add_region(point_region)
            self.assertFalse(point_region._closed)
            display_specifier.buffered_data_source.remove_region(point_region)
            self.assertTrue(point_region._closed)

    def test_removing_data_item_closes_point_region(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            point_region = Region.PointRegion()
            display_specifier.buffered_data_source.add_region(point_region)
            self.assertFalse(point_region._closed)
            document_model.remove_data_item(data_item)
            self.assertTrue(point_region._closed)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
