# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Region
from nion.swift.model import Storage
from nion.ui import Test


class TestRegionClass(unittest.TestCase):

    def test_changing_point_region_updates_drawn_graphic(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        point_region = Region.PointRegion()
        data_item.add_region(point_region)
        drawn_graphic = data_item.displays[0].drawn_graphics[0]
        self.assertEqual(point_region.position, drawn_graphic.position)
        point_region.position = (0.3, 0.7)
        self.assertEqual(point_region.position, drawn_graphic.position)

    def test_changing_drawn_graphic_updates_point_region(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        point_region = Region.PointRegion()
        data_item.add_region(point_region)
        drawn_graphic = data_item.displays[0].drawn_graphics[0]
        self.assertEqual(point_region.position, drawn_graphic.position)
        drawn_graphic.position = (0.3, 0.7)
        self.assertEqual(point_region.position, drawn_graphic.position)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
