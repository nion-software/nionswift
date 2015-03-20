import datetime
import logging
import threading
import time
import unittest

import numpy as np

from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import HardwareSource
from nion.swift.model import ImportExportManager
from nion.swift import Application
from nion.swift import DocumentController
from nion.ui import Test


class SimpleHardwareSource(HardwareSource.HardwareSource):

    def __init__(self, sleep=0.05):
        super(SimpleHardwareSource, self).__init__("simple_hardware_source", "SimpleHardwareSource")
        self.sleep = sleep
        self.image = np.zeros(256)

    def make_data_element(self):
        return {
            "version": 1,
            "data": self.image,
            "properties": {
                "exposure": 0.5,
                "autostem": { "high_tension_v": 140000 },
                "hardware_source_name": "hardware source",
                "hardware_source_id": "simple_hardware_source"
            }
        }

    def acquire_data_elements(self):
        self.image += 1.0
        time.sleep(self.sleep)
        data_element = self.make_data_element()
        return [data_element]


class ScanHardwareSource(HardwareSource.HardwareSource):

    def __init__(self, sleep=0.02):
        super(ScanHardwareSource, self).__init__("scan_hardware_source", "ScanHardwareSource")
        self.sleep = sleep
        self.image = np.zeros((256, 256))
        self.frame_index = 0
        self.top = True
        self.scanning = False
        self.suspended = False
        self.suspend_event = threading.Event()
        self.channel_count = 2
        self.channel_ids = ["a", "b"]
        self.channel_names = ["A", "B"]
        self.channel_enabled = [True, False]

    def make_data_element(self, channel_index=0, sub_area=None):
        if sub_area is not None:
            data = np.zeros(self.image.shape, self.image.dtype)
            data_slice = slice(sub_area[0][0], sub_area[0][0] + sub_area[1][0]), slice(sub_area[0][1], sub_area[0][1] + sub_area[1][1])
            data[data_slice] = self.image[data_slice]
        else:
            data = self.image.copy()
        return {
            "version": 1,
            "data": data,
            "channel_id": self.channel_ids[channel_index],
            "channel_name": self.channel_names[channel_index],
            "properties": {
                "exposure": 0.5,
                "autostem": { "high_tension_v": 140000 },
                "hardware_source_name": "hardware source",
                "hardware_source_id": "scan_hardware_source"
            }
        }

    def acquire_data_elements(self):
        self.image += 1.0
        time.sleep(self.__current_sleep)
        data_elements = list()
        for channel_index in range(self.channel_count):
            if self.channel_enabled[channel_index]:
                if self.top:
                    sub_area = (0, 0), (128, 256)
                else:
                    sub_area = (128, 0), (256, 256)
                data_element = self.make_data_element(channel_index, sub_area)
                if self.top:
                    data_element["state"] = "partial"
                    data_element["sub_area"] = sub_area
                    data_element["properties"]["complete"] = False
                    data_element["properties"]["frame_index"] = self.frame_index
                    self.frame_index += 1
                else:
                    data_element["state"] = "complete"
                    data_element["sub_area"] = sub_area
                    data_element["properties"]["complete"] = True
                    data_element["properties"]["frame_index"] = self.frame_index
                data_elements.append(data_element)
        self.top = not self.top
        return data_elements

    def start_acquisition(self):
        self.__current_sleep = self.sleep
        self.scanning = True
        if self.is_recording:
            self.sleep = 0.04
            self.top = True
        else:
            self.sleep = 0.02
            self.top = True

    def stop_acquisition(self):
        self.scanning = False

    def suspend_acquisition(self):
        self.suspended = True
        self.suspend_event.set()

    def resume_acquisition(self):
        self.suspended = False


def _test_acquiring_frames_with_generator_produces_correct_frame_numbers(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    frame0 = hardware_source.get_next_data_elements_to_finish()[0]["properties"]["frame_index"]
    frame1 = hardware_source.get_next_data_elements_to_finish()[0]["properties"]["frame_index"]
    frame3 = hardware_source.get_next_data_elements_to_start()[0]["properties"]["frame_index"]
    frame5 = hardware_source.get_next_data_elements_to_start()[0]["properties"]["frame_index"]
    testcase.assertEqual((1, 3, 5), (frame1 - frame0, frame3 - frame0, frame5 - frame0))
    hardware_source.abort_playing()
    hardware_source.close()

def _test_acquire_multiple_frames_reuses_same_data_item(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    testcase.assertTrue(hardware_source.is_playing)
    with hardware_source.get_data_element_generator(False) as data_element_generator:
        data_element_generator()
        data_element_generator()
        data_element_generator()
        data_element_generator()
    hardware_source.abort_playing()
    document_controller.periodic()  # data items queued to be added from background thread get added here
    start_time = time.time()
    while hardware_source.is_playing:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    testcase.assertFalse(hardware_source.is_playing)
    document_controller.periodic()  # data items queued to be added from background thread get added here
    testcase.assertEqual(len(document_controller.document_model.data_items), 1)
    hardware_source.close()

def _test_simple_hardware_start_and_stop_actually_stops_acquisition(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    start_time = time.time()
    while not hardware_source.is_playing:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    hardware_source.stop_playing()
    start_time = time.time()
    while hardware_source.is_playing:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    hardware_source.close()

def _test_simple_hardware_start_and_abort_works_as_expected(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    testcase.assertTrue(hardware_source.is_playing)
    hardware_source.abort_playing()
    start_time = time.time()
    while hardware_source.is_playing:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    hardware_source.close()

def _test_record_only_acquires_one_item(testcase, hardware_source, document_controller):
    hardware_source.start_recording()
    testcase.assertFalse(hardware_source.is_playing)
    testcase.assertTrue(hardware_source.is_recording)
    start_time = time.time()
    while hardware_source.is_recording:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    testcase.assertFalse(hardware_source.is_playing)
    document_controller.periodic()
    testcase.assertEqual(len(document_controller.document_model.data_items), 1)
    hardware_source.close()

def _test_record_during_view_records_one_item_and_keeps_viewing(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    # start playing, grab a few frames
    with hardware_source.get_data_element_generator(False) as data_element_generator:
        data_element_generator()
        data_element_generator()
    hardware_source.start_recording()
    # wait for recording to start
    start_time = time.time()
    while not hardware_source.is_recording:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    testcase.assertTrue(hardware_source.is_playing)
    # wait for recording to stop
    start_time = time.time()
    while hardware_source.is_recording:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    testcase.assertTrue(hardware_source.is_playing)
    with hardware_source.get_data_element_generator(False) as data_element_generator:
        data_element_generator()
    hardware_source.abort_playing()
    document_controller.periodic()
    testcase.assertEqual(len(document_controller.document_model.data_items), 2)
    hardware_source.close()

def _test_abort_record_during_view_returns_to_view(testcase, hardware_source, document_controller):
    # first start playing
    hardware_source.start_playing()
    with hardware_source.get_data_element_generator(False) as data_element_generator:
        data_element_generator()
    document_controller.periodic()
    # now start recording
    hardware_source.start_recording()
    # wait for recording to start
    start_time = time.time()
    while not hardware_source.is_recording:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    hardware_source.abort_recording()
    with hardware_source.get_data_element_generator(False) as data_element_generator:
        data_element_generator()
    # clean up
    hardware_source.abort_playing()
    hardware_source.close()

def _test_view_reuses_single_data_item(testcase, hardware_source, document_controller):
    document_model = document_controller.document_model
    testcase.assertEqual(len(document_model.data_items), 0)
    # play the first time
    hardware_source.start_playing()
    with hardware_source.get_data_element_generator(False) as data_element_generator:
        data_element_generator()
    hardware_source.stop_playing()
    # wait for it to stop
    start_time = time.time()
    while hardware_source.is_playing:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    document_controller.periodic()  # data items get added on the ui thread. give it a time slice.
    testcase.assertEqual(len(document_model.data_items), 1)
    data_item = document_model.data_items[0]
    testcase.assertFalse(data_item.is_live)
    frame_index = data_item.data_sources[0].metadata.get("hardware_source")["frame_index"]
    # play the second time. it should make a copy of the first data item and use the original.
    hardware_source.start_playing()
    with hardware_source.get_data_element_generator(False) as data_element_generator:
        data_element_generator()
    hardware_source.stop_playing()
    # wait for it to stop
    start_time = time.time()
    while hardware_source.is_playing:
        time.sleep(0.01)
        testcase.assertTrue(time.time() - start_time < 3.0)
    document_controller.periodic()  # data items get added on the ui thread. give it a time slice.
    testcase.assertEqual(len(document_model.data_items), 2)
    data_item = document_model.data_items[0]
    copied_data_item = document_model.data_items[1]
    new_frame_index = data_item.data_sources[0].metadata.get("hardware_source")["frame_index"]
    copied_frame_index = copied_data_item.data_sources[0].metadata.get("hardware_source")["frame_index"]
    testcase.assertNotEqual(frame_index, new_frame_index)
    testcase.assertEqual(frame_index, copied_frame_index)
    hardware_source.close()

def _test_get_next_data_elements_to_finish_returns_full_frames(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    data_element = hardware_source.get_next_data_elements_to_finish()[0]
    hardware_source.abort_playing()
    testcase.assertNotEqual(data_element["data"][0, 0], 0)
    testcase.assertNotEqual(data_element["data"][-1, -1], 0)
    testcase.assertIsNone(data_element.get("sub_area"))
    hardware_source.close()


class TestHardwareSourceClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)
        HardwareSource.HardwareSourceManager()._reset()

    def tearDown(self):
        pass

    def __acquire_one(self, document_controller, hardware_source):
        hardware_source.start_playing()
        start_time = time.time()
        while not hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.stop_playing()
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        document_controller.periodic()

    def __record_one(self, document_controller, hardware_source):
        hardware_source.start_recording()
        start_time = time.time()
        while hardware_source.is_recording:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        document_controller.periodic()

    def __setup_simple_hardware_source(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source = SimpleHardwareSource()
        hardware_source.exposure = 0.01
        HardwareSource.HardwareSourceManager().register_hardware_source(hardware_source)
        return document_controller, document_model, hardware_source

    def __setup_scan_hardware_source(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source = ScanHardwareSource()
        hardware_source.exposure = 0.01
        hardware_source.stages_per_frame = 2
        hardware_source.blanked = False
        hardware_source.positioned = False
        HardwareSource.HardwareSourceManager().register_hardware_source(hardware_source)
        return document_controller, document_model, hardware_source

    def test_registering_and_unregistering_works_as_expected(self):
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(hardware_source)
        self.assertEqual(len(hardware_source_manager.hardware_sources), 1)
        hardware_source_manager.unregister_hardware_source(hardware_source)
        self.assertIsNone(hardware_source_manager.get_hardware_source_for_hardware_source_id("simple_hardware_source"))

    def test_hardware_source_aliases_works(self):
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        simple_hardware_source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(simple_hardware_source)
        hardware_source_manager.make_instrument_alias(simple_hardware_source.hardware_source_id, "testalias", "Test1")
        hardware_source_manager.make_instrument_alias(simple_hardware_source.hardware_source_id, "testalias2", "Test2")
        hardware_source_manager.make_instrument_alias("testalias", "testalias3", "Test3")
        hardware_source_manager.make_instrument_alias("testalias2", "testalias4", "Test4")
        self.assertEqual(hardware_source_manager.get_hardware_source_for_hardware_source_id("testalias").hardware_source_id, simple_hardware_source.hardware_source_id)
        self.assertEqual(hardware_source_manager.get_hardware_source_for_hardware_source_id("testalias2").hardware_source_id, simple_hardware_source.hardware_source_id)
        self.assertEqual(hardware_source_manager.get_hardware_source_for_hardware_source_id("testalias3").hardware_source_id, simple_hardware_source.hardware_source_id)
        hardware_source_manager.unregister_hardware_source(simple_hardware_source)

    ## STANDARD ACQUISITION TESTS ##
    # Search for the tag above when adding tests to this section.

    def test_acquiring_frames_with_generator_produces_correct_frame_numbers(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        _test_acquiring_frames_with_generator_produces_correct_frame_numbers(self, hardware_source, document_controller)

    def test_acquiring_frames_as_partials_with_generator_produces_correct_frame_numbers(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        _test_acquiring_frames_with_generator_produces_correct_frame_numbers(self, hardware_source, document_controller)

    def test_acquire_multiple_frames_reuses_same_data_item(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        _test_acquire_multiple_frames_reuses_same_data_item(self, hardware_source, document_controller)

    def test_acquire_multiple_frames_as_partials_reuses_same_data_item(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        _test_acquire_multiple_frames_reuses_same_data_item(self, hardware_source, document_controller)

    def test_simple_hardware_start_and_stop_actually_stops_acquisition(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        _test_simple_hardware_start_and_stop_actually_stops_acquisition(self, hardware_source, document_controller)

    def test_simple_hardware_start_and_abort_works_as_expected(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        _test_simple_hardware_start_and_abort_works_as_expected(self, hardware_source, document_controller)

    def test_record_only_acquires_one_item(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        _test_record_only_acquires_one_item(self, hardware_source, document_controller)

    def test_record_during_view_records_one_item_and_keeps_viewing(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        _test_record_during_view_records_one_item_and_keeps_viewing(self, hardware_source, document_controller)

    def test_abort_record_during_view_returns_to_view(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        _test_abort_record_during_view_returns_to_view(self, hardware_source, document_controller)

    def test_view_reuses_single_data_item(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        _test_view_reuses_single_data_item(self, hardware_source, document_controller)

    def test_get_next_data_elements_to_finish_returns_full_frames(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        _test_get_next_data_elements_to_finish_returns_full_frames(self, hardware_source, document_controller)

    def test_record_scan_during_view_suspends_the_view(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        # first start playing
        hardware_source.start_playing()
        start_time = time.time()
        while not hardware_source.scanning:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        self.assertFalse(hardware_source.suspended)
        # now start recording
        hardware_source.sleep = 0.06
        hardware_source.start_recording()
        hardware_source.suspend_event.wait(3.0)
        self.assertTrue(hardware_source.suspended)
        start_time = time.time()
        while hardware_source.is_recording:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        time.sleep(0.01)
        self.assertFalse(hardware_source.suspended)
        # clean up
        hardware_source.abort_playing()
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.close()

    def test_view_reuses_externally_configured_item(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        hardware_source_id = hardware_source.hardware_source_id
        self.assertEqual(len(document_model.data_items), 0)
        data_item = DataItem.DataItem(np.ones(256) + 1)
        document_model.append_data_item(data_item)
        document_controller.workspace_controller.setup_channel(hardware_source_id, None, hardware_source_id, data_item)
        # at this point the data item contains 2.0. the acquisition will produce a 1.0.
        # the 2.0 will get copied to data_item 1 and the 1.0 will be replaced into data_item 0.
        self.__acquire_one(document_controller, hardware_source)
        self.assertEqual(len(document_model.data_items), 2)  # old one is copied
        self.assertAlmostEqual(document_model.data_items[0].data_sources[0].data[0], 1.0)
        self.assertAlmostEqual(document_model.data_items[1].data_sources[0].data[0], 2.0)

    def test_setup_channel_configures_tags_correctly(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        hardware_source_id = hardware_source.hardware_source_id
        channel_id = "aaa"
        view_id = "bbb"
        self.assertEqual(len(document_model.data_items), 0)
        data_item = DataItem.DataItem(np.ones(256) + 1)
        document_model.append_data_item(data_item)
        document_controller.workspace_controller.setup_channel(hardware_source_id, channel_id, view_id, data_item)
        # these tags are required for the workspace to work right. not sure how else to test this.
        self.assertEqual(data_item.maybe_data_source.metadata.get("hardware_source")["hardware_source_id"], hardware_source_id)
        self.assertEqual(data_item.maybe_data_source.metadata.get("hardware_source")["channel_id"], channel_id)
        self.assertEqual(data_item.maybe_data_source.metadata.get("hardware_source")["view_id"], view_id)

    def test_partial_acquisition_only_updates_sub_area(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        data_item = DataItem.DataItem(np.zeros((256, 256)) + 16)
        document_model.append_data_item(data_item)
        document_controller.workspace_controller.setup_channel(hardware_source.hardware_source_id, "a", str(hardware_source.hardware_source_id), data_item)
        hardware_source.exposure = 0.02
        hardware_source.start_playing()
        time.sleep(0.01)
        hardware_source.abort_playing()
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        self.assertEqual(len(document_model.data_items), 1)
        data = document_model.data_items[0].data_sources[0].data
        self.assertAlmostEqual(data[0, 0], 1.0)
        self.assertAlmostEqual(data[128, 0], 16.0)

    def test_standard_data_element_constructs_metadata_with_hardware_source_as_dict(self):
        data_element = SimpleHardwareSource().make_data_element()
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        metadata = data_item.data_sources[0].metadata
        self.assertTrue(isinstance(metadata.get("hardware_source"), dict))

    def test_updating_existing_data_item_updates_creation_even_if_an_updated_date_is_not_supplied(self):
        data_element = SimpleHardwareSource().make_data_element()
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        data_item.created = datetime.datetime(2000, 06, 30)
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        self.assertEqual(data_item.created.year, datetime.datetime.utcnow().year)

    def test_channel_id_and_name_and_index_are_empty_for_simple_hardware_source(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        self.__acquire_one(document_controller, hardware_source)
        data_item0 = document_model.data_items[0]
        buffered_data_source = data_item0.data_sources[0]
        hardware_source_metadata = buffered_data_source.metadata.get("hardware_source", dict())
        self.assertEqual(data_item0.title, hardware_source.display_name)
        self.assertEqual(hardware_source_metadata.get("channel_index"), 0)
        self.assertIsNone(hardware_source_metadata.get("channel_id"))
        self.assertIsNone(hardware_source_metadata.get("channel_name"))

    def test_channel_id_and_name_and_index_are_correct_for_view(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        self.__acquire_one(document_controller, hardware_source)
        data_item0 = document_model.data_items[0]
        buffered_data_source = data_item0.data_sources[0]
        hardware_source_metadata = buffered_data_source.metadata.get("hardware_source", dict())
        self.assertEqual(data_item0.title, "%s (%s)" % (hardware_source.display_name, "A"))
        self.assertEqual(hardware_source_metadata.get("channel_index"), 0)
        self.assertEqual(hardware_source_metadata.get("channel_id"), "a")
        self.assertEqual(hardware_source_metadata.get("channel_name"), "A")

    def test_channel_id_and_name_and_index_are_correct_for_multiview(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        hardware_source.channel_enabled = (True, True)
        self.__acquire_one(document_controller, hardware_source)
        data_item0 = document_model.data_items[0]
        buffered_data_source0 = data_item0.data_sources[0]
        hardware_source_metadata0 = buffered_data_source0.metadata.get("hardware_source", dict())
        self.assertEqual(data_item0.title, "%s (%s)" % (hardware_source.display_name, "A"))
        self.assertEqual(hardware_source_metadata0.get("channel_index"), 0)
        self.assertEqual(hardware_source_metadata0.get("channel_id"), "a")
        self.assertEqual(hardware_source_metadata0.get("channel_name"), "A")
        data_item1 = document_model.data_items[1]
        buffered_data_source1 = data_item1.data_sources[0]
        hardware_source_metadata1 = buffered_data_source1.metadata.get("hardware_source", dict())
        self.assertEqual(data_item1.title, "%s (%s)" % (hardware_source.display_name, "B"))
        self.assertEqual(hardware_source_metadata1.get("channel_index"), 1)
        self.assertEqual(hardware_source_metadata1.get("channel_id"), "b")
        self.assertEqual(hardware_source_metadata1.get("channel_name"), "B")

    def test_multiview_reuse_second_channel_by_id_not_index(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        hardware_source.channel_enabled = (True, True)
        self.__acquire_one(document_controller, hardware_source)
        buffered_data_source0 = document_model.data_items[0].data_sources[0]
        buffered_data_source1 = document_model.data_items[1].data_sources[0]
        self.assertAlmostEqual(buffered_data_source0.data[0, 0], 1.0)  # 1.0 because top half of two part partial acquisition
        self.assertAlmostEqual(buffered_data_source1.data[0, 0], 1.0)
        self.assertAlmostEqual(buffered_data_source0.data[-1, -1], 2.0)  # 2.0 because bottom half of two part partial acquisition
        self.assertAlmostEqual(buffered_data_source1.data[-1, -1], 2.0)
        hardware_source.channel_enabled = (False, True)
        self.__acquire_one(document_controller, hardware_source)
        self.assertAlmostEqual(buffered_data_source0.data[0, 0], 1.0)
        self.assertAlmostEqual(buffered_data_source1.data[0, 0], 3.0)
        self.assertAlmostEqual(buffered_data_source0.data[-1, -1], 2.0)
        self.assertAlmostEqual(buffered_data_source1.data[-1, -1], 4.0)

    def test_assessed_flag_is_not_set_for_viewed_data(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        self.__acquire_one(document_controller, hardware_source)
        self.assertIsNone(document_model.data_items[0].metadata.get("assessed"))

    def test_assessed_flag_is_false_for_recorded_data(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        self.__record_one(document_controller, hardware_source)
        self.assertFalse(document_model.data_items[0].metadata.get("assessed", True))

    def test_restarting_view_in_same_session_preserves_dependent_data_connections(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        self.__acquire_one(document_controller, hardware_source)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
        document_controller.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "invert-operation")
        document_controller.periodic()
        document_model.recompute_all()
        modified = document_model.data_items[1].modified
        value = document_model.data_items[1].data_sources[0].data_and_calibration.data[0]
        acq_value = document_model.data_items[0].data_sources[0].data_and_calibration.data[0]
        self.assertEqual(acq_value, 1.0)
        self.assertEqual(value, -acq_value)
        self.__acquire_one(document_controller, hardware_source)
        document_controller.periodic()
        document_model.recompute_all()
        self.assertNotEqual(modified, document_model.data_items[1].modified)
        value = document_model.data_items[1].data_sources[0].data_and_calibration.data[0]
        acq_value = document_model.data_items[0].data_sources[0].data_and_calibration.data[0]
        self.assertEqual(acq_value, 2.0)
        self.assertEqual(value, -acq_value)

    def test_restarting_view_after_reload_preserves_dependent_data_connections(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        self.__acquire_one(document_controller, hardware_source)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
        document_controller.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "invert-operation")
        document_controller.periodic()
        document_model.recompute_all()
        document_model.start_new_session()
        document_controller.workspace_controller._clear_channel_data_items()
        self.__acquire_one(document_controller, hardware_source)
        document_controller.periodic()
        document_model.recompute_all()
        self.assertEqual(len(document_model.data_items), 3)
        value = document_model.data_items[1].data_sources[0].data_and_calibration.data[0]
        acq_value0 = document_model.data_items[0].data_sources[0].data_and_calibration.data[0]
        acq_value2 = document_model.data_items[2].data_sources[0].data_and_calibration.data[0]
        self.assertEqual(acq_value0, 2.0)
        self.assertEqual(acq_value2, 1.0)
        self.assertEqual(value, -acq_value0)

if __name__ == '__main__':
    unittest.main()
