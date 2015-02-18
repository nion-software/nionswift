import datetime
import logging
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
                "extra_high_tension": 140000,
                "hardware_source": "hardware source",
                "hardware_source_id": "simple_hardware_source"
            }
        }

    def acquire_data_elements(self):
        self.image += 1.0
        time.sleep(self.sleep)
        data_element = self.make_data_element()
        return [data_element]


class ScanHardwareSource(HardwareSource.HardwareSource):

    def __init__(self, sleep=0.01):
        super(ScanHardwareSource, self).__init__("scan_hardware_source", "ScanHardwareSource")
        self.sleep = sleep
        self.image = np.zeros((256, 256))
        self.top = True
        self.scanning = False
        self.suspended = False
        self.channel_count = 2
        self.channel_ids = ["a", "b"]
        self.channel_names = ["A", "B"]
        self.channel_enabled = [True, False]

    def make_data_element(self, channel_index=0):
        return {
            "version": 1,
            "data": self.image,
            "channel_id": self.channel_ids[channel_index],
            "channel_name": self.channel_names[channel_index],
            "properties": {
                "exposure": 0.5,
                "extra_high_tension": 140000,
                "hardware_source": "hardware source",
                "hardware_source_id": "scan_hardware_source"
            }
        }

    def acquire_data_elements(self):
        self.image += 1.0
        time.sleep(self.sleep)
        data_elements = list()
        for channel_index in range(self.channel_count):
            if self.channel_enabled[channel_index]:
                data_element = self.make_data_element(channel_index)
                if self.top:
                    data_element["state"] = "partial"
                    data_element["sub_area"] = (0, 0), (128, 256)
                else:
                    data_element["state"] = "complete"
                    data_element["sub_area"] = (0, 0), (256, 256)
                data_elements.append(data_element)
        self.top = not self.top
        return data_elements

    def start_acquisition(self):
        self.scanning = True

    def stop_acquisition(self):
        self.scanning = False

    def suspend_acquisition(self):
        self.suspended = True

    def resume_acquisition(self):
        self.suspended = False


class DummyWorkspaceController(object):

    def __init__(self, document_model):
        self.document_controller = self  # hack so that document_controller.document_model works
        self.document_model = document_model

    def sync_channels_to_data_items(self, channels, hardware_source_id, view_id, display_name):
        data_item_set = {}
        for channel in channels:
            data_item_set[channel.index] = DataItem.DataItem()
        return data_item_set

    def queue_task(self, task):
        pass


class TestHardwareSourceClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def __acquire_one(self, document_controller, hardware_source):
        hardware_source.start_playing(document_controller.workspace_controller)
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

    def __setup_simple_hardware_source(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source = SimpleHardwareSource()
        hardware_source.exposure = 0.01
        return document_controller, document_model, hardware_source

    def __setup_scan_hardware_source(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source = ScanHardwareSource()
        hardware_source.exposure = 0.01
        hardware_source.stages_per_frame = 2
        hardware_source.blanked = False
        hardware_source.positioned = False
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

    def test_events(self):
        document_model = DocumentModel.DocumentModel()
        workspace_controller = DummyWorkspaceController(document_model)
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = SimpleHardwareSource(0.02)
        hardware_source_manager.register_hardware_source(hardware_source)
        self.assertEqual(len(hardware_source_manager.hardware_sources), 1)
        hardware_source.start_playing(workspace_controller)
        frame_index_ref = [0]
        new_data_elements = list()
        def handle_new_data_elements(data_elements):
            new_data_elements[:] = list()
            new_data_elements.extend(data_elements)
            frame_index_ref[0] = data_elements[0].get("properties").get("frame_index", 0)
        viewed_data_elements_available_event_listener = hardware_source.viewed_data_elements_available_event.listen(handle_new_data_elements)
        while frame_index_ref[0] < 4:
            time.sleep(0.01)
        tl_pixel = new_data_elements[0]["data"][0]
        # print "got %d images in 1s"%tl_pixel
        self.assertTrue(3.0 < tl_pixel < 7.0)
        viewed_data_elements_available_event_listener.close()
        hardware_source.abort_playing()
        hardware_source_manager.unregister_hardware_source(hardware_source)

    def test_acquiring_three_frames_works(self):
        # stopping acquisition should not clear session
        document_model = DocumentModel.DocumentModel()
        workspace_controller = DummyWorkspaceController(document_model)
        hardware_source = SimpleHardwareSource(0.01)
        hardware_source.start_playing(workspace_controller)
        frame_index_ref = [0]
        def handle_new_data_elements(data_elements):
            frame_index_ref[0] = data_elements[0].get("properties").get("frame_index", 0)
        viewed_data_elements_available_event_listener = hardware_source.viewed_data_elements_available_event.listen(handle_new_data_elements)
        while frame_index_ref[0] < 4:
            time.sleep(0.01)
        viewed_data_elements_available_event_listener.close()
        hardware_source.abort_playing()
        hardware_source.close()

    def test_acquiring_three_frames_as_partials_works(self):
        # stopping acquisition should not clear session
        document_model = DocumentModel.DocumentModel()
        workspace_controller = DummyWorkspaceController(document_model)
        hardware_source = ScanHardwareSource()
        hardware_source.start_playing(workspace_controller)
        frame_index_ref = [0]
        def handle_new_data_elements(data_elements):
            frame_index_ref[0] = data_elements[0].get("properties").get("frame_index", 0)
        viewed_data_elements_available_event_listener = hardware_source.viewed_data_elements_available_event.listen(handle_new_data_elements)
        while frame_index_ref[0] < 4:
            time.sleep(0.01)
        viewed_data_elements_available_event_listener.close()
        hardware_source.abort_playing()
        hardware_source.close()

    def test_acquiring_frames_with_generator_produces_correct_frame_numbers(self):
        document_model = DocumentModel.DocumentModel()
        workspace_controller = DummyWorkspaceController(document_model)
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = SimpleHardwareSource(0.02)
        hardware_source_manager.register_hardware_source(hardware_source)
        hardware_source.start_playing(workspace_controller)
        # startup of generator will wait for frame 0
        # grab the next two (un-synchronized frames) frame 1 and frame 2
        with HardwareSource.get_data_element_generator_by_id("simple_hardware_source", False) as data_element_generator:
            frame1 = data_element_generator()["properties"]["frame_index"]
            frame2 = data_element_generator()["properties"]["frame_index"]
        # startup of this generator will wait for frame 3
        # grab the next synchronized frames, frame 5 and frame 7
        with HardwareSource.get_data_element_generator_by_id("simple_hardware_source", True) as data_element_generator:
            frame5 = data_element_generator()["properties"]["frame_index"]
            frame7 = data_element_generator()["properties"]["frame_index"]
        hardware_source_manager.unregister_hardware_source(hardware_source)
        self.assertEqual((1, 2, 5, 7), (frame1, frame2, frame5, frame7))
        hardware_source.abort_playing()

    def test_simple_hardware_start_and_wait_acquires_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(hardware_source)
        self.assertEqual(len(document_model.data_items), 0)
        hardware_source.start_playing(document_controller.workspace_controller)
        self.assertTrue(hardware_source.is_playing)
        frame_index_ref = [0]
        def handle_new_data_elements(data_elements):
            frame_index_ref[0] = data_elements[0].get("properties").get("frame_index", 0)
        viewed_data_elements_available_event_listener = hardware_source.viewed_data_elements_available_event.listen(handle_new_data_elements)
        start_time = time.time()
        while frame_index_ref[0] < 4:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        viewed_data_elements_available_event_listener.close()
        hardware_source.abort_playing()
        document_controller.periodic()  # data items queued to be added from background thread get added here
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        self.assertFalse(hardware_source.is_playing)
        document_controller.periodic()  # data items queued to be added from background thread get added here
        self.assertEqual(len(document_model.data_items), 1)
        hardware_source.close()
        document_controller.close()

    def test_simple_hardware_start_and_stop_actually_stops_acquisition(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        hardware_source = hardware_source_manager.get_hardware_source_for_hardware_source_id("simple_hardware_source")
        hardware_source.start_playing(document_controller.workspace_controller)
        start_time = time.time()
        while not hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.stop_playing()
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.close()
        document_controller.close()

    def test_simple_hardware_start_and_abort_works_as_expected(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(hardware_source)
        hardware_source.start_playing(document_controller.workspace_controller)
        self.assertTrue(hardware_source.is_playing)
        hardware_source.abort_playing()
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.close()
        document_controller.close()

    def test_record_only_acquires_one_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(hardware_source)
        hardware_source.start_recording(document_controller.workspace_controller)
        self.assertFalse(hardware_source.is_playing)
        self.assertTrue(hardware_source.is_recording)
        start_time = time.time()
        while hardware_source.is_recording:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        self.assertFalse(hardware_source.is_playing)
        hardware_source.close()
        document_controller.close()

    def test_record_scan_during_view_records_one_item_and_keeps_viewing(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = ScanHardwareSource()
        hardware_source_manager.register_hardware_source(hardware_source)
        hardware_source.start_playing(document_controller.workspace_controller)
        # start playing, grab a few frames
        frame_index_ref = [0]
        def handle_viewed_data_elements(data_elements):
            if len(data_elements) > 0:
                if data_elements[0].get("state") == "complete":
                    frame_index_ref[0] = data_elements[0].get("properties").get("frame_index", 0)
        record_index_ref = [-1]
        def handle_recorded_data_elements(data_elements):
            if len(data_elements) > 0:
                if data_elements[0].get("state") == "complete":
                    record_index_ref[0] = data_elements[0].get("properties").get("frame_index", 0)
        viewed_data_elements_available_event_listener = hardware_source.viewed_data_elements_available_event.listen(handle_viewed_data_elements)
        recorded_data_elements_available_event_listener = hardware_source.recorded_data_elements_available_event.listen(handle_recorded_data_elements)
        start_time = time.time()
        while frame_index_ref[0] < 2:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        # now do a record
        self.assertEqual(record_index_ref[0], -1)
        hardware_source.start_recording(document_controller.workspace_controller)
        self.assertTrue(hardware_source.is_playing)
        self.assertTrue(hardware_source.is_recording)
        start_time = time.time()
        while hardware_source.is_recording:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        self.assertTrue(hardware_source.is_playing)
        self.assertFalse(hardware_source.is_recording)
        self.assertEqual(record_index_ref[0], 0)
        # make sure we're still viewing
        start_time = time.time()
        start_index = frame_index_ref[0]
        while frame_index_ref[0] < start_index + 2:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        # clean up
        hardware_source.abort_playing()
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        viewed_data_elements_available_event_listener.close()
        recorded_data_elements_available_event_listener.close()
        hardware_source.close()
        document_controller.close()

    def test_record_scan_during_view_suspends_the_view(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = ScanHardwareSource()
        hardware_source_manager.register_hardware_source(hardware_source)
        # first start playing
        hardware_source.start_playing(document_controller.workspace_controller)
        start_time = time.time()
        while not hardware_source.scanning:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        self.assertFalse(hardware_source.suspended)
        # now start recording
        hardware_source.sleep = 0.02
        hardware_source.start_recording(document_controller.workspace_controller)
        time.sleep(0.01)  # give recording a chance to start
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
        document_controller.close()

    def test_view_only_puts_all_frames_into_a_single_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = ScanHardwareSource()
        frame_index_ref = [-1]
        def handle_viewed_data_elements(data_elements):
            if len(data_elements) > 0:
                if data_elements[0].get("state") == "complete":
                    frame_index_ref[0] = data_elements[0].get("properties").get("frame_index", 0)
        viewed_data_elements_available_event_listener = hardware_source.viewed_data_elements_available_event.listen(handle_viewed_data_elements)
        self.assertEqual(len(document_model.data_items), 0)
        hardware_source.start_playing(document_controller.workspace_controller)
        start_time = time.time()
        while frame_index_ref[0] < 3:
            time.sleep(0.01)
            document_controller.periodic()
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.abort_playing()
        document_controller.periodic()  # data items get added on the ui thread. give it a time slice.
        self.assertEqual(len(document_model.data_items), 1)
        viewed_data_elements_available_event_listener.close()
        hardware_source.close()
        document_controller.close()

    def test_record_only_put_data_into_a_single_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = ScanHardwareSource()
        self.assertEqual(len(document_model.data_items), 0)
        hardware_source.start_recording(document_controller.workspace_controller)
        start_time = time.time()
        while hardware_source.is_recording:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        document_controller.periodic()  # data items get added on the ui thread. give it a time slice.
        self.assertEqual(len(document_model.data_items), 1)
        hardware_source.close()
        document_controller.close()

    def test_view_with_record_puts_all_frames_into_two_data_items(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = ScanHardwareSource()
        frame_index_ref = [-1]
        def handle_viewed_data_elements(data_elements):
            if len(data_elements) > 0:
                if data_elements[0].get("state") == "complete":
                    frame_index_ref[0] = data_elements[0].get("properties").get("frame_index", 0)
        viewed_data_elements_available_event_listener = hardware_source.viewed_data_elements_available_event.listen(handle_viewed_data_elements)
        self.assertEqual(len(document_model.data_items), 0)
        hardware_source.start_playing(document_controller.workspace_controller)
        start_time = time.time()
        while frame_index_ref[0] < 3:
            time.sleep(0.01)
            document_controller.periodic()
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.start_recording(document_controller.workspace_controller)
        start_time = time.time()
        while hardware_source.is_recording:
            time.sleep(0.01)
            document_controller.periodic()
            self.assertTrue(time.time() - start_time < 3.0)
        start_time = time.time()
        while frame_index_ref[0] < 6:
            time.sleep(0.01)
            document_controller.periodic()
            self.assertTrue(time.time() - start_time < 3.0)
        document_controller.periodic()  # data items get added on the ui thread. give it a time slice.
        self.assertEqual(len(document_model.data_items), 2)
        hardware_source.close()
        viewed_data_elements_available_event_listener.close()
        document_controller.close()

    def test_view_reuses_single_data_item(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        hardware_source = ScanHardwareSource()
        self.assertEqual(len(document_model.data_items), 0)
        # play the first time
        hardware_source.start_playing(document_controller.workspace_controller)
        start_time = time.time()
        while not hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.stop_playing()
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        document_controller.periodic()  # data items get added on the ui thread. give it a time slice.
        self.assertEqual(len(document_model.data_items), 1)
        data_item = document_model.data_items[0]
        self.assertFalse(data_item.is_live)
        data_value = data_item.data_sources[0].data[0, 0]
        # play the second time. it should make a copy of the first data item and use the original.
        hardware_source.start_playing(document_controller.workspace_controller)
        start_time = time.time()
        while not hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.stop_playing()
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        document_controller.periodic()  # data items get added on the ui thread. give it a time slice.
        self.assertEqual(len(document_model.data_items), 2)
        new_data_value = data_item.data_sources[0].data[0, 0]
        self.assertNotAlmostEqual(data_value, new_data_value)
        hardware_source.close()
        document_controller.close()

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
        self.assertAlmostEqual(buffered_data_source0.data[0, 0], 2.0)  # 2.0 because two part partial acquisition
        self.assertAlmostEqual(buffered_data_source1.data[0, 0], 2.0)
        hardware_source.channel_enabled = (False, True)
        self.__acquire_one(document_controller, hardware_source)
        self.assertAlmostEqual(buffered_data_source0.data[0, 0], 2.0)
        self.assertAlmostEqual(buffered_data_source1.data[0, 0], 4.0)

if __name__ == '__main__':
    unittest.main()
