# standard libraries
import copy
import datetime
import logging
import os
import unittest
import uuid

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift.model import DataItem
from nion.swift.model import ImportExportManager
from nion.swift.model import Utility


class TestImportExportManagerClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_convert_data_element_records_time_zone_in_data_item_metadata(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = Utility.get_current_datetime_item()
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertIsNotNone(data_item.created)
        self.assertEqual(data_item.metadata["description"]["time_zone"]["tz"], data_element["datetime_modified"]["tz"])
        self.assertEqual(data_item.metadata["description"]["time_zone"]["dst"], data_element["datetime_modified"]["dst"])

    def test_convert_data_element_sets_timezone_and_timezone_offset_if_present(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = {'tz': '+0300', 'dst': '+60', 'local_datetime': '2015-06-10T19:31:52.780511', 'timezone': 'Europe/Athens'}
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertIsNotNone(data_item.created)
        self.assertEqual(data_item.timezone, "Europe/Athens")
        self.assertEqual(data_item.timezone_offset, "+0300")

    def test_date_formats(self):
        data_item = DataItem.DataItem()
        data_item.created = datetime.datetime(2013, 11, 18, 14, 5, 4, 0)
        self.assertIsNotNone(data_item.created_local_as_string)

    def test_sub_area_size_change(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertEqual(display_specifier.data_item.dimensional_shape, (16, 16))
        self.assertEqual(display_specifier.data_item.data_dtype, numpy.double)
        data_element["data"] = numpy.zeros((8, 8), dtype=numpy.double)
        data_element["sub_area"] = ((0,0), (4, 8))
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        self.assertEqual(display_specifier.data_item.dimensional_shape, (8, 8))
        self.assertEqual(display_specifier.data_item.data_dtype, numpy.double)
        data_element["data"] = numpy.zeros((8, 8), dtype=numpy.float)
        data_element["sub_area"] = ((0,0), (4, 8))
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        self.assertEqual(display_specifier.data_item.dimensional_shape, (8, 8))
        self.assertEqual(display_specifier.data_item.data_dtype, numpy.float)

    def test_ndata_write_to_then_read_from_temp_file(self):
        current_working_directory = os.getcwd()
        file_path = os.path.join(current_working_directory, "__file.ndata")
        handler = ImportExportManager.NDataImportExportHandler("ndata1-io-handler", "ndata", ["ndata"])
        data_item = DataItem.DataItem(numpy.zeros((16, 16), dtype=numpy.double))
        handler.write(None, data_item, file_path, "ndata")
        self.assertTrue(os.path.exists(file_path))
        try:
            data_items = handler.read_data_items(None, "ndata", file_path)
            self.assertEqual(len(data_items), 1)
            data_item = data_items[0]
        finally:
            os.remove(file_path)

    def test_get_writers_for_empty_data_item_returns_valid_list(self):
        data_item = DataItem.DataItem()
        writers = ImportExportManager.ImportExportManager().get_writers_for_data_item(data_item)
        self.assertEqual(len(writers), 0)

    def test_get_writers_for_float_2d_data_item_returns_valid_list(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.float))
        writers = ImportExportManager.ImportExportManager().get_writers_for_data_item(data_item)
        self.assertTrue(len(writers) > 0)

    def test_data_element_date_gets_set_as_data_item_created_date(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = {'tz': '+0300', 'dst': '+60', 'local_datetime': '2015-06-10T19:31:52.780511'}
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertIsNotNone(data_item.created)
        self.assertEqual(data_item.metadata["description"]["time_zone"]["tz"], "+0300")
        self.assertEqual(data_item.metadata["description"]["time_zone"]["dst"], "+60")
        local_offset_seconds = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds()))
        match = datetime.datetime(year=2015, month=6, day=10, hour=19 - 3, minute=31, second=52, microsecond=780511) + datetime.timedelta(seconds=local_offset_seconds)
        self.assertEqual(data_item.created_local, match)

    def test_data_element_with_uuid_assigns_uuid_to_data_item(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element_uuid = uuid.uuid4()
        data_element["uuid"] = str(data_element_uuid)
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertEqual(data_item.uuid, data_element_uuid)

    def test_creating_data_element_with_sequence_data_makes_correct_data_item(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((4, 16, 16), dtype=numpy.double)
        data_element["is_sequence"] = True
        data_element["collection_dimension_count"] = 0
        data_element["datum_dimension_count"] = 2
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertEqual(data_item.is_sequence, True)
        self.assertEqual(data_item.collection_dimension_count, 0)
        self.assertEqual(data_item.datum_dimension_count, 2)
        self.assertEqual(data_item.xdata.is_sequence, True)
        self.assertEqual(data_item.xdata.collection_dimension_count, 0)
        self.assertEqual(data_item.xdata.datum_dimension_count, 2)

    def test_creating_data_element_with_sequence_and_implicit_datum_size_data_makes_correct_data_item(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((4, 16, 16), dtype=numpy.double)
        data_element["is_sequence"] = True
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertEqual(data_item.is_sequence, True)
        self.assertEqual(data_item.collection_dimension_count, 0)
        self.assertEqual(data_item.datum_dimension_count, 2)
        self.assertEqual(data_item.xdata.is_sequence, True)
        self.assertEqual(data_item.xdata.collection_dimension_count, 0)
        self.assertEqual(data_item.xdata.datum_dimension_count, 2)

    def test_data_element_to_extended_data_conversion(self):
        data = numpy.ones((8, 6), numpy.int)
        intensity_calibration = Calibration.Calibration(offset=1, scale=1.1, units="one")
        dimensional_calibrations = [Calibration.Calibration(offset=2, scale=2.1, units="two"), Calibration.Calibration(offset=3, scale=2.2, units="two")]
        metadata = {"hardware_source": {"one": 1, "two": "b"}}
        timestamp = datetime.datetime.now()
        data_descriptor = DataAndMetadata.DataDescriptor(is_sequence=False, collection_dimension_count=1, datum_dimension_count=1)
        xdata = DataAndMetadata.new_data_and_metadata(data, intensity_calibration=intensity_calibration, dimensional_calibrations=dimensional_calibrations, metadata=metadata, timestamp=timestamp, data_descriptor=data_descriptor)
        data_element = ImportExportManager.create_data_element_from_extended_data(xdata)
        new_xdata = ImportExportManager.convert_data_element_to_data_and_metadata(data_element)
        self.assertTrue(numpy.array_equal(data, new_xdata.data))
        self.assertNotEqual(id(new_xdata.intensity_calibration), id(intensity_calibration))
        self.assertEqual(new_xdata.intensity_calibration, intensity_calibration)
        self.assertNotEqual(id(new_xdata.dimensional_calibrations[0]), id(dimensional_calibrations[0]))
        self.assertEqual(new_xdata.dimensional_calibrations, dimensional_calibrations)
        self.assertNotEqual(id(new_xdata.metadata), id(metadata))
        # the handling of time zone in xdata is probably not correct right now; this is a temporary workaround
        # the reason it is probably not correct is that the timezone for a data item is recorded in the data
        # item metadata, not the buffered data source metadata. however, here it is stored with the extended
        # data which eventually gets put into the buffered data source metadata.
        xdata_metadata_without_description = copy.deepcopy(new_xdata.metadata)
        xdata_metadata_without_description.pop("description")
        self.assertEqual(xdata_metadata_without_description, metadata)
        self.assertNotEqual(id(new_xdata.data_descriptor), id(data_descriptor))
        self.assertEqual(new_xdata.data_descriptor, data_descriptor)

    def test_data_item_to_data_element_includes_time_zone(self):
        # created/modified are utc; timezone is specified in metadata/description/time_zone
        data_item = DataItem.DataItem(numpy.zeros((16, 16)))
        data_item.created = datetime.datetime(2013, 6, 18, 14, 5, 4, 0)  # always utc
        data_item.timezone = "Europe/Athens"
        data_item.timezone_offset = "+0300"
        data_item._set_modified(datetime.datetime(2013, 6, 18, 14, 5, 4, 0))  # always utc
        data_item.metadata = {"description": {"time_zone": {"tz": "+0300", "dst": "+60"}}}
        data_element = ImportExportManager.create_data_element_from_data_item(data_item, include_data=False)
        self.assertEqual(data_element["datetime_modified"], {"dst": "+60", "local_datetime": "2013-06-18T17:05:04", 'tz': "+0300", 'timezone': "Europe/Athens"})

    def test_extended_data_to_data_element_includes_time_zone(self):
        # extended data timestamp is utc; timezone is specified in metadata/description/time_zone
        data = numpy.ones((8, 6), numpy.int)
        metadata = {"description": {"time_zone": {"tz": "+0300", "dst": "+60"}}}
        timestamp = datetime.datetime(2013, 11, 18, 14, 5, 4, 0)
        xdata = DataAndMetadata.new_data_and_metadata(data, metadata=metadata, timestamp=timestamp)
        data_element = ImportExportManager.create_data_element_from_extended_data(xdata)
        self.assertEqual(data_element["datetime_modified"], {"dst": "+60", "local_datetime": "2013-11-18T17:05:04", 'tz': "+0300"})

    def test_data_element_to_data_item_includes_time_zone(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = {'tz': '+0300', 'dst': '+60', 'local_datetime': '2015-06-10T19:31:52.780511'}
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertEqual(data_item.metadata["description"]["time_zone"]["tz"], "+0300")
        self.assertEqual(data_item.metadata["description"]["time_zone"]["dst"], "+60")
        self.assertEqual(str(data_item.created), "2015-06-10 16:31:52.780511")

    def test_data_element_to_extended_data_includes_time_zone(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = {'tz': '+0300', 'dst': '+60', 'local_datetime': '2015-06-10T19:31:52.780511'}
        xdata = ImportExportManager.convert_data_element_to_data_and_metadata(data_element)
        self.assertEqual(xdata.metadata["description"]["time_zone"]["tz"], "+0300")
        self.assertEqual(xdata.metadata["description"]["time_zone"]["dst"], "+60")
        self.assertEqual(str(xdata.timestamp), "2015-06-10 16:31:52.780511")

    def test_time_zone_in_extended_data_to_data_element_to_data_item_conversion(self):
        # test the whole path, redundant?
        data = numpy.ones((8, 6), numpy.int)
        metadata = {"description": {"time_zone": {"tz": "+0300", "dst": "+60"}}, "hardware_source": {"one": 1, "two": "b"}}
        timestamp = datetime.datetime(2013, 11, 18, 14, 5, 4, 1)
        xdata = DataAndMetadata.new_data_and_metadata(data, metadata=metadata, timestamp=timestamp)
        data_element = ImportExportManager.create_data_element_from_extended_data(xdata)
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertEqual(data_item.metadata["description"]["time_zone"]["tz"], "+0300")
        self.assertEqual(data_item.metadata["description"]["time_zone"]["dst"], "+60")
        self.assertEqual("2013-11-18 14:05:04.000001", str(data_item.created))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
