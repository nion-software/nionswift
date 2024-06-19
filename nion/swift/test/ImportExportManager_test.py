# standard libraries
import contextlib
import datetime
import json
import logging
import os
import pathlib
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
from nion.swift.test import TestContext
from nion.utils import DateTime


class TestImportExportManagerClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_convert_data_element_records_time_zone_in_data_item_metadata(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = Utility.get_current_datetime_item()
        with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
            self.assertIsNotNone(data_item.created)
            self.assertEqual(data_item.timezone_offset, data_element["datetime_modified"]["tz"])

    def test_convert_data_element_sets_timezone_and_timezone_offset_if_present(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = {'tz': '+0300', 'dst': '+60', 'local_datetime': '2015-06-10T19:31:52.780511', 'timezone': 'Europe/Athens'}
        with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
            self.assertIsNotNone(data_item.created)
            self.assertEqual(data_item.timezone, "Europe/Athens")
            self.assertEqual(data_item.timezone_offset, "+0300")

    def test_date_formats(self):
        data_item = DataItem.DataItem()
        with contextlib.closing(data_item):
            data_item.created = datetime.datetime(2013, 11, 18, 14, 5, 4, 0)
            self.assertIsNotNone(data_item.created_local_as_string)

    def test_sub_area_size_change(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_element = dict()
            data_element["version"] = 1
            data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
            data_item = ImportExportManager.create_data_item_from_data_element(data_element)
            document_model.append_data_item(data_item)
            self.assertEqual(data_item.dimensional_shape, (16, 16))
            self.assertEqual(data_item.data_dtype, numpy.double)
            data_element["data"] = numpy.zeros((8, 8), dtype=numpy.double)
            data_element["sub_area"] = ((0,0), (4, 8))
            ImportExportManager.update_data_item_from_data_element(data_item, data_element)
            self.assertEqual(data_item.dimensional_shape, (8, 8))
            self.assertEqual(data_item.data_dtype, numpy.double)
            data_element["data"] = numpy.zeros((8, 8), dtype=float)
            data_element["sub_area"] = ((0,0), (4, 8))
            ImportExportManager.update_data_item_from_data_element(data_item, data_element)
            self.assertEqual(data_item.dimensional_shape, (8, 8))
            self.assertEqual(data_item.data_dtype, float)

    def test_ndata_write_to_then_read_from_temp_file(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            current_working_directory = os.getcwd()
            file_path = os.path.join(current_working_directory, "__file.ndata")
            handler = ImportExportManager.NDataImportExportHandler("ndata1-io-handler", "ndata", ["ndata"])
            data_item = DataItem.DataItem(numpy.zeros((16, 16), dtype=numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            handler.write_display_item(display_item, pathlib.Path(file_path), "ndata")
            self.assertTrue(os.path.exists(file_path))
            try:
                data_items = handler.read_data_items("ndata", pathlib.Path(file_path))
                self.assertEqual(len(data_items), 1)
                data_item = data_items[0]
                for data_item in data_items:
                    data_item.close()
            finally:
                os.remove(file_path)

    def test_npy_write_to_then_read_from_temp_file(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            current_working_directory = os.getcwd()
            file_path_npy = os.path.join(current_working_directory, "__file.npy")
            file_path_json = os.path.join(current_working_directory, "__file.json")
            numpy.save(file_path_npy, numpy.zeros((16, 16)))
            with open(file_path_json, "w") as f:
                json.dump({"version": 1}, f)
            handler = ImportExportManager.NumPyImportExportHandler("numpy-io-handler", "npy", ["npy"])
            try:
                data_items = handler.read_data_items("npy", pathlib.Path(file_path_npy))
                self.assertEqual(len(data_items), 1)
                data_item = data_items[0]
                for data_item in data_items:
                    data_item.close()
            finally:
                os.remove(file_path_npy)
                os.remove(file_path_json)

    def test_standard_io_write_to_then_read_from_temp_file(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            current_working_directory = os.getcwd()
            extensions = ("jpeg", "png", "gif", "bmp", "webp")
            for extension in extensions:
                file_path = os.path.join(current_working_directory, f"__file.{extension}")
                handler = ImportExportManager.StandardImportExportHandler(f"{extension}-io-handler", extension, [extension])
                data_item = DataItem.DataItem(numpy.zeros((16, 16), dtype=numpy.double))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                handler.write_display_item(display_item, pathlib.Path(file_path), extension)
                self.assertTrue(os.path.exists(file_path))
                try:
                    data_items = handler.read_data_items(extension, pathlib.Path(file_path))
                    self.assertEqual(len(data_items), 1)
                    for data_item in data_items:
                        data_item.close()
                finally:
                    os.remove(file_path)

    def test_get_writers_for_empty_data_item_returns_valid_list(self):
        data_item = DataItem.DataItem()
        with contextlib.closing(data_item):
            writers = ImportExportManager.ImportExportManager().get_writers_for_data_item(data_item)
            self.assertEqual(len(writers), 0)

    def test_get_writers_for_float_2d_data_item_returns_valid_list(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), float))
        with contextlib.closing(data_item):
            writers = ImportExportManager.ImportExportManager().get_writers_for_data_item(data_item)
            self.assertTrue(len(writers) > 0)

    def test_data_element_date_gets_set_as_data_item_created_date(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = {'tz': '+0300', 'dst': '+60', 'local_datetime': '2015-06-10T19:31:52.780511'}
        with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
            self.assertIsNotNone(data_item.created)
            self.assertEqual(data_item.timezone_offset, "+0300")
            local_offset_seconds = int(round((datetime.datetime.now() - DateTime.utcnow()).total_seconds()))
            # check both matches for DST
            match1 = datetime.datetime(year=2015, month=6, day=10, hour=19 - 3, minute=31, second=52, microsecond=780511) + datetime.timedelta(seconds=local_offset_seconds)
            match2 = datetime.datetime(year=2015, month=6, day=10, hour=19 - 3, minute=31, second=52, microsecond=780511) + datetime.timedelta(seconds=local_offset_seconds + 3600)
            self.assertTrue(data_item.created_local == match1 or data_item.created_local == match2)

    def test_data_element_with_uuid_assigns_uuid_to_data_item(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element_uuid = uuid.uuid4()
        data_element["uuid"] = str(data_element_uuid)
        with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
            self.assertEqual(data_item.uuid, data_element_uuid)

    def test_creating_data_element_with_sequence_data_makes_correct_data_item(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((4, 16, 16), dtype=numpy.double)
        data_element["is_sequence"] = True
        data_element["collection_dimension_count"] = 0
        data_element["datum_dimension_count"] = 2
        with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
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
        with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
            self.assertEqual(data_item.is_sequence, True)
            self.assertEqual(data_item.collection_dimension_count, 0)
            self.assertEqual(data_item.datum_dimension_count, 2)
            self.assertEqual(data_item.xdata.is_sequence, True)
            self.assertEqual(data_item.xdata.collection_dimension_count, 0)
            self.assertEqual(data_item.xdata.datum_dimension_count, 2)

    def test_data_element_to_extended_data_conversion(self):
        data = numpy.ones((8, 6), int)
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
        self.assertEqual(tuple(new_xdata.dimensional_calibrations), tuple(dimensional_calibrations))
        self.assertNotEqual(id(new_xdata.metadata), id(metadata))
        self.assertEqual(new_xdata.metadata, metadata)
        self.assertNotEqual(id(new_xdata.data_descriptor), id(data_descriptor))
        self.assertEqual(new_xdata.data_descriptor, data_descriptor)

    def test_data_item_to_data_element_includes_time_zone(self):
        # created/modified are utc; timezone is specified in metadata/description/time_zone
        data_item = DataItem.DataItem(numpy.zeros((16, 16)))
        with contextlib.closing(data_item):
            data_item.created = datetime.datetime(2013, 6, 18, 14, 5, 4, 0)  # always utc
            data_item.timezone = "Europe/Athens"
            data_item.timezone_offset = "+0300"
            data_item._set_modified(datetime.datetime(2013, 6, 18, 14, 5, 4, 0))  # always utc
            data_item.metadata = {"description": {"time_zone": {"tz": "+0300", "dst": "+60"}}}
            data_element = ImportExportManager.create_data_element_from_data_item(data_item, include_data=False)
            self.assertEqual(data_element["datetime_modified"], {"dst": "+60", "local_datetime": "2013-06-18T17:05:04", 'tz': "+0300", 'timezone': "Europe/Athens"})

    def test_extended_data_to_data_element_includes_time_zone(self):
        # extended data timestamp is utc; timezone is specified in metadata/description/time_zone
        data = numpy.ones((8, 6), int)
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
        with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
            self.assertEqual(data_item.timezone_offset, "+0300")
            self.assertEqual(str(data_item.created), "2015-06-10 16:31:52.780511")

    def test_data_element_to_extended_data_includes_time_zone(self):
        data_element = dict()
        data_element["version"] = 1
        data_element["data"] = numpy.zeros((16, 16), dtype=numpy.double)
        data_element["datetime_modified"] = {'tz': '+0300', 'dst': '+60', 'local_datetime': '2015-06-10T19:31:52.780511'}
        xdata = ImportExportManager.convert_data_element_to_data_and_metadata(data_element)
        self.assertEqual(xdata.timezone_offset, "+0300")
        self.assertEqual(str(xdata.timestamp), "2015-06-10 16:31:52.780511")

    def test_time_zone_in_extended_data_to_data_element_to_data_item_conversion(self):
        # test the whole path, redundant?
        data = numpy.ones((8, 6), int)
        metadata = {"description": {"time_zone": {"tz": "+0300", "dst": "+60"}}, "hardware_source": {"one": 1, "two": "b"}}
        timestamp = datetime.datetime(2013, 11, 18, 14, 5, 4, 1)
        xdata = DataAndMetadata.new_data_and_metadata(data, metadata=metadata, timestamp=timestamp)
        data_element = ImportExportManager.create_data_element_from_extended_data(xdata)
        with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
            self.assertEqual(data_item.metadata["description"]["time_zone"]["tz"], "+0300")
            self.assertEqual(data_item.metadata["description"]["time_zone"]["dst"], "+60")
            self.assertEqual("2013-11-18 14:05:04.000001", str(data_item.created))

    def test_csv1_exporter_handles_multi_layer_display_item_with_same_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.full((50, ), 0, dtype=numpy.uint32))
            data_item.intensity_calibration = Calibration.Calibration(offset=10, scale=2)
            data_item2 = DataItem.DataItem(numpy.full((100, ), 1, dtype=numpy.uint32))
            data_item2.intensity_calibration = Calibration.Calibration(offset=5, scale=2)
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.append_display_data_channel_for_data_item(data_item2)
            current_working_directory = os.getcwd()
            file_path = os.path.join(current_working_directory, "__file.csv")
            handler = ImportExportManager.CSV1ImportExportHandler("csv1-io-handler", "CSV 1D", ["csv"])
            handler.write_display_item(display_item, pathlib.Path(file_path), "csv")
            self.assertTrue(os.path.exists(file_path))
            try:
                saved_data = numpy.genfromtxt(file_path, delimiter=", ")
                self.assertSequenceEqual(saved_data.shape, (max(data_item.xdata.data_shape[0], data_item2.xdata.data_shape[0]), 3))
                self.assertTrue(numpy.allclose(saved_data[:, 0], numpy.linspace(0, 99, 100)))
                self.assertTrue(numpy.allclose(saved_data[:50, 1], 10))
                self.assertTrue(numpy.allclose(saved_data[:, 2], 7))
            finally:
                os.remove(file_path)

    def test_csv1_exporter_handles_multi_layer_display_item_with_different_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.full((50, ), 0, dtype=numpy.uint32))
            data_item.dimensional_calibrations = [Calibration.Calibration(offset=0, scale=1, units="eV")]
            data_item.intensity_calibration = Calibration.Calibration(offset=10, scale=2)
            data_item2 = DataItem.DataItem(numpy.full((100, ), 1, dtype=numpy.uint32))
            data_item2.dimensional_calibrations = [Calibration.Calibration(offset=-10, scale=2, units="eV")]
            data_item2.intensity_calibration = Calibration.Calibration(offset=5, scale=2)
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_item.append_display_data_channel_for_data_item(data_item2)
            current_working_directory = os.getcwd()
            file_path = os.path.join(current_working_directory, "__file.csv")
            handler = ImportExportManager.CSV1ImportExportHandler("csv1-io-handler", "CSV 1D", ["csv"])
            handler.write_display_item(display_item, pathlib.Path(file_path), "csv")
            self.assertTrue(os.path.exists(file_path))
            try:
                saved_data = numpy.genfromtxt(file_path, delimiter=", ")
                self.assertSequenceEqual(saved_data.shape, (max(data_item.xdata.data_shape[0], data_item2.xdata.data_shape[0]), 4))
                self.assertTrue(numpy.allclose(saved_data[:50, 0], numpy.linspace(0, 49, 50)))
                self.assertTrue(numpy.allclose(saved_data[:50, 1], 10))
                self.assertTrue(numpy.allclose(saved_data[:, 2], numpy.linspace(-10, 188, 100)))
                self.assertTrue(numpy.allclose(saved_data[:, 3], 7))
            finally:
                os.remove(file_path)

    def test_data_item_to_data_element_produces_json_compatible_dict(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16)))
        with contextlib.closing(data_item):
            data_item.created = datetime.datetime(2013, 6, 18, 14, 5, 4, 0)  # always utc
            data_item.timezone = "Europe/Athens"
            data_item.timezone_offset = "+0300"
            data_item.source_file_path = "/path/to/source/file"
            data_item._set_modified(datetime.datetime(2013, 6, 18, 14, 5, 4, 0))  # always utc
            data_item.metadata = {"description": {"time_zone": {"tz": "+0300", "dst": "+60"}}}
            data_element = ImportExportManager.create_data_element_from_data_item(data_item, include_data=False)
            json.dumps(data_element)

    def test_data_item_to_data_element_and_back_keeps_large_format_flag(self):
        data_item = DataItem.DataItem(numpy.zeros((4, 4, 4)), large_format=True)
        with contextlib.closing(data_item):
            data_element = ImportExportManager.create_data_element_from_data_item(data_item, include_data=True)
            self.assertTrue(data_element.get("large_format"))
            with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
                self.assertTrue(data_item.large_format)

    def test_importing_rgb_does_not_set_large_format(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8, 4), dtype=float))
        with contextlib.closing(data_item):
            data_item_rgb = DataItem.DataItem(numpy.zeros((8, 8, 4), dtype=numpy.uint8))
            with contextlib.closing(data_item_rgb):
                data_element = ImportExportManager.create_data_element_from_data_item(data_item, include_data=True)
                data_element_rgb = ImportExportManager.create_data_element_from_data_item(data_item_rgb, include_data=True)
                data_element.pop("large_format")
                data_element_rgb.pop("large_format")
                with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element)) as data_item:
                    with contextlib.closing(ImportExportManager.create_data_item_from_data_element(data_element_rgb)) as data_item_rgb:
                        self.assertTrue(data_item.large_format)
                        self.assertFalse(data_item_rgb.large_format)

    def test_importing_large_numpy_file_sets_large_format_flag(self):
        current_working_directory = os.getcwd()
        file_path_npy = os.path.join(current_working_directory, "__file.npy")
        numpy.save(file_path_npy, numpy.zeros((4, 4, 4)))
        handler = ImportExportManager.NumPyImportExportHandler("numpy-io-handler", "npy", ["npy"])
        try:
            data_items = handler.read_data_items("npy", pathlib.Path(file_path_npy))
            self.assertEqual(len(data_items), 1)
            data_item = data_items[0]
            self.assertTrue(data_item.large_format)
            for data_item in data_items:
                data_item.close()
        finally:
            os.remove(file_path_npy)

    def test_data_item_with_numpy_bool_to_data_element_produces_json_compatible_dict(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16)))
        data_item.large_format = numpy.prod((2,3,4), dtype=numpy.int64) > 10  # produces a numpy.bool_
        with contextlib.closing(data_item):
            data_element = ImportExportManager.create_data_element_from_data_item(data_item, include_data=False)
            json.dumps(data_element)

    def test_csv_exporter_handles_3d_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((10, 10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            current_working_directory = os.getcwd()
            file_path = os.path.join(current_working_directory, "__file.csv")
            handler = ImportExportManager.CSVImportExportHandler("csv-io-handler", "CSV Raw", ["csv"])
            handler.write_display_item(display_item, pathlib.Path(file_path), "csv")
            self.assertFalse(os.path.exists(file_path))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
