import contextlib
import copy
import datetime
import threading
import time
import unittest

import numpy

from nion.data import DataAndMetadata
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import HardwareSource
from nion.swift.model import ImportExportManager
from nion.swift.model import Utility
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import Facade
from nion.ui import DrawingContext
from nion.ui import TestUI
from nion.utils import Geometry


Facade.initialize()


class SimpleAcquisitionTask(HardwareSource.AcquisitionTask):

    def __init__(self, is_continuous, sleep, image=None):
        super().__init__(is_continuous)
        self.sleep = sleep
        self.image = image if image is not None else numpy.zeros(256)

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

    def _acquire_data_elements(self):
        self.image += 1.0
        time.sleep(self.sleep)
        data_element = self.make_data_element()
        return [data_element]


class SimpleHardwareSource(HardwareSource.HardwareSource):

    def __init__(self, sleep=0.05):
        super().__init__("simple_hardware_source", "SimpleHardwareSource")
        self.add_data_channel()
        self.sleep = sleep
        self.image = numpy.zeros(256)

    def _create_acquisition_view_task(self) -> SimpleAcquisitionTask:
        return SimpleAcquisitionTask(True, self.sleep, self.image)

    def _create_acquisition_record_task(self) -> SimpleAcquisitionTask:
        return SimpleAcquisitionTask(False, self.sleep, self.image)


class LinePlotAcquisitionTask(HardwareSource.AcquisitionTask):

    def __init__(self, shape, is_continuous, sleep):
        super().__init__(is_continuous)
        self.shape = shape
        self.sleep = sleep
        self.frame_number = 0

    def make_data_element(self):
        return {
            "version": 1,
            "data": numpy.zeros(self.shape),
            "frame_number": self.frame_number,
            "collection_dimension_count": 1 if len(self.shape) > 1 else 0,
            "datum_dimension_count": 1,
            "properties": {
                "exposure": 0.5,
                "autostem": { "high_tension_v": 140000 },
                "hardware_source_name": "hardware source",
                "hardware_source_id": "simple_hardware_source"
            }
        }

    def _acquire_data_elements(self):
        self.frame_number += 1
        time.sleep(self.sleep)
        data_element = self.make_data_element()
        return [data_element]


class LinePlotHardwareSource(HardwareSource.HardwareSource):

    def __init__(self, shape, processed, sleep=0.05):
        super().__init__("described_hardware_source", "DescribedHardwareSource")
        self.add_data_channel()
        if processed:
            self.add_channel_processor(0, HardwareSource.SumProcessor(((0.0, 0.0), (1.0, 1.0))))
        self.sleep = sleep
        self.shape = shape

    def _create_acquisition_view_task(self) -> LinePlotAcquisitionTask:
        return LinePlotAcquisitionTask(self.shape, True, self.sleep)

    def _create_acquisition_record_task(self) -> LinePlotAcquisitionTask:
        return LinePlotAcquisitionTask(self.shape, False, self.sleep)


class SummedHardwareSource(HardwareSource.HardwareSource):

    def __init__(self, sleep=0.05):
        super().__init__("summed_hardware_source", "SummedHardwareSource")
        self.add_data_channel()
        self.add_channel_processor(0, HardwareSource.SumProcessor(((0.0, 0.0), (1.0, 1.0))))
        self.sleep = sleep
        self.image = numpy.zeros((256, 256))

    def _create_acquisition_view_task(self) -> SimpleAcquisitionTask:
        return SimpleAcquisitionTask(True, self.sleep, self.image)

    def _create_acquisition_record_task(self) -> SimpleAcquisitionTask:
        return SimpleAcquisitionTask(False, self.sleep, self.image)


class ScanAcquisitionTask(HardwareSource.AcquisitionTask):

    def __init__(self, is_continuous, sleep, channel_enabled_list=None, scanning_ref=None, suspended_ref=None, suspended_event=None, image=None):
        super().__init__(is_continuous)
        self.__is_continuous = is_continuous
        self.sleep = sleep
        self.image = image if image is not None else numpy.zeros((256, 256))
        self.frame_index = 0
        self.top = True
        self.scanning_ref = scanning_ref
        self.suspended_ref = suspended_ref
        self.suspend_event = suspended_event
        self.channel_ids = ["a", "b"]
        self.channel_names = ["A", "B"]
        self.channel_enabled = channel_enabled_list

    def make_data_element(self, channel_index=0, sub_area=None):
        if sub_area is not None:
            data = numpy.zeros(self.image.shape, self.image.dtype)
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

    def _start_acquisition(self) -> bool:
        if not super()._start_acquisition():
            return False
        self.__current_sleep = self.sleep
        self.scanning_ref[0] = True
        if self.__is_continuous:
            self.sleep = 0.04
            self.top = True
        else:
            self.sleep = 0.02
            self.top = True
        return True

    def _acquire_data_elements(self):
        self.image += 1.0
        time.sleep(self.__current_sleep)
        data_elements = list()
        for channel_index in range(2):
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
                else:
                    data_element["state"] = "complete"
                    data_element["sub_area"] = sub_area
                    data_element["properties"]["complete"] = True
                    data_element["properties"]["frame_index"] = self.frame_index
                    self.frame_index += 1
                data_element["properties"]["is_continuous"] = self.__is_continuous
                data_elements.append(data_element)
        self.top = not self.top
        return data_elements

    def _suspend_acquisition(self) -> None:
        self.suspended_ref[0] = True
        self.suspend_event.set()

    def _resume_acquisition(self):
        self.suspended_ref[0] = False

    def _stop_acquisition(self) -> None:
        self.scanning_ref[0] = False
        super()._stop_acquisition()


class ScanHardwareSource(HardwareSource.HardwareSource):

    def __init__(self, sleep=0.02):
        super().__init__("scan_hardware_source", "ScanHardwareSource")
        self.add_data_channel("a", "A")
        self.add_data_channel("b", "B")
        self.sleep = sleep
        self.channel_enabled_list = [True, False]
        self.scanning_ref = [False]
        self.suspended_ref = [False]
        self.suspend_event = threading.Event()
        self.image = numpy.zeros((256, 256))

    @property
    def scanning(self):
        return self.scanning_ref[0]

    @scanning.setter
    def scanning(self, value):
        self.scanning_ref[0] = value

    @property
    def suspended(self):
        return self.suspended_ref[0]

    @suspended.setter
    def suspended(self, value):
        self.suspended_ref[0] = value

    def _create_acquisition_view_task(self) -> ScanAcquisitionTask:
        return ScanAcquisitionTask(True, self.sleep, self.channel_enabled_list, self.scanning_ref, self.suspended_ref, self.suspend_event, self.image)

    def _create_acquisition_record_task(self) -> ScanAcquisitionTask:
        return ScanAcquisitionTask(False, self.sleep, self.channel_enabled_list, self.scanning_ref, self.suspended_ref, self.suspend_event, self.image)


def _test_acquiring_frames_with_generator_produces_correct_frame_numbers(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    try:
        frame0 = hardware_source.get_next_xdatas_to_finish()[0].metadata["hardware_source"]["frame_index"]
        frame1 = hardware_source.get_next_xdatas_to_finish()[0].metadata["hardware_source"]["frame_index"]
        frame3 = hardware_source.get_next_xdatas_to_start()[0].metadata["hardware_source"]["frame_index"]
        frame5 = hardware_source.get_next_xdatas_to_start()[0].metadata["hardware_source"]["frame_index"]
        testcase.assertEqual((1, 3, 5), (frame1 - frame0, frame3 - frame0, frame5 - frame0))
    finally:
        hardware_source.abort_playing(sync_timeout=3.0)

def _test_acquire_multiple_frames_reuses_same_data_item(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    try:
        testcase.assertTrue(hardware_source.is_playing)
        hardware_source.get_next_xdatas_to_finish()
        hardware_source.get_next_xdatas_to_finish()
        hardware_source.get_next_xdatas_to_finish()
        hardware_source.get_next_xdatas_to_finish()
    finally:
        hardware_source.abort_playing(sync_timeout=3.0)
    document_controller.periodic()  # data items queued to be added from background thread get added here
    testcase.assertEqual(len(document_controller.document_model.data_items), 1)

def _test_simple_hardware_start_and_stop_actually_stops_acquisition(testcase, hardware_source, document_controller):
    try:
        hardware_source.start_playing(sync_timeout=3.0)
        hardware_source.stop_playing(sync_timeout=3.0)
    except Exception as e:
        hardware_source.abort_playing(sync_timeout=3.0)

def _test_simple_hardware_start_and_abort_works_as_expected(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    try:
        testcase.assertTrue(hardware_source.is_playing)
    finally:
        hardware_source.abort_playing(sync_timeout=3.0)

def _test_record_only_acquires_one_item(testcase, hardware_source, document_controller):
    # the definition is that the 'view' image is always acquired; there should only
    # be a single new 'record' image though. the 'record' image should not have a
    # category of 'temporary'; the 'view' image should.
    hardware_source.start_recording()
    try:
        testcase.assertFalse(hardware_source.is_playing)
        testcase.assertTrue(hardware_source.is_recording)
        hardware_source.get_next_xdatas_to_finish(timeout=3.0)
    finally:
        hardware_source.abort_recording(sync_timeout=3.0)
    testcase.assertFalse(hardware_source.is_playing)
    document_controller.periodic()
    testcase.assertEqual(len(document_controller.document_model.data_items), 1)
    testcase.assertEqual(document_controller.document_model.data_items[0].category, "temporary")
    # UPDATE: record data is now in data_elements; it is neither temporary or not. it's just data.

def _test_record_during_view_records_one_item_and_keeps_viewing(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    try:
        # start playing, grab a few frames
        hardware_source.get_next_xdatas_to_finish()
        hardware_source.get_next_xdatas_to_finish()
        hardware_source.start_recording(sync_timeout=3.0)
        extended_data_list = hardware_source.get_next_xdatas_to_start()
        testcase.assertTrue(hardware_source.is_playing)
        # wait for recording to stop
        start_time = time.time()
        while hardware_source.is_recording:
            time.sleep(0.01)
            testcase.assertTrue(time.time() - start_time < 3.0)
        testcase.assertTrue(hardware_source.is_playing)
        hardware_source.get_next_xdatas_to_finish()
    finally:
        hardware_source.abort_playing(sync_timeout=3.0)
    document_controller.periodic()
    testcase.assertEqual(len(document_controller.document_model.data_items), 1)
    # ensure the recorded data is different from the view data.
    testcase.assertNotEqual(document_controller.document_model.data_items[0].metadata["hardware_source"]["frame_index"], extended_data_list[0].metadata["hardware_source"]["frame_index"])

def _test_abort_record_during_view_returns_to_view(testcase, hardware_source, document_controller):
    # first start playing
    hardware_source.start_playing()
    try:
        hardware_source.get_next_xdatas_to_finish()
        document_controller.periodic()
        # now start recording
        hardware_source.start_recording(sync_timeout=3.0)
        hardware_source.abort_recording()
        hardware_source.get_next_xdatas_to_finish()
    finally:
        # clean up
        hardware_source.abort_playing(sync_timeout=3.0)
        hardware_source.abort_recording(sync_timeout=3.0)

def _test_view_reuses_single_data_item(testcase, hardware_source, document_controller):
    document_model = document_controller.document_model
    testcase.assertEqual(len(document_model.data_items), 0)
    # play the first time
    hardware_source.start_playing()
    try:
        hardware_source.get_next_xdatas_to_finish()
    finally:
        hardware_source.stop_playing(sync_timeout=3.0)
    document_controller.periodic()  # data items get added on the ui thread. give it a time slice.
    testcase.assertEqual(len(document_model.data_items), 1)
    data_item = document_model.data_items[0]
    testcase.assertFalse(data_item.is_live)
    frame_index = data_item.metadata.get("hardware_source")["frame_index"]
    # play the second time. it should make a copy of the first data item and use the original.
    new_data_item = copy.deepcopy(document_model.data_items[0])
    document_model.append_data_item(new_data_item)
    hardware_source.start_playing()
    try:
        hardware_source.get_next_xdatas_to_start()
    finally:
        hardware_source.stop_playing(sync_timeout=3.0)
    document_controller.periodic()  # data items get added on the ui thread. give it a time slice.
    testcase.assertEqual(len(document_model.data_items), 2)
    data_item = document_model.data_items[0]
    copied_data_item = document_model.data_items[1]
    new_frame_index = data_item.metadata.get("hardware_source")["frame_index"]
    copied_frame_index = copied_data_item.metadata.get("hardware_source")["frame_index"]
    testcase.assertNotEqual(frame_index, new_frame_index)
    testcase.assertEqual(frame_index, copied_frame_index)

def _test_get_next_data_elements_to_finish_returns_full_frames(testcase, hardware_source, document_controller):
    hardware_source.start_playing()
    try:
        extended_data_list = hardware_source.get_next_xdatas_to_finish()
    finally:
        hardware_source.abort_playing(sync_timeout=3.0)
    document_controller.periodic()
    testcase.assertNotEqual(extended_data_list[0].data[0, 0], 0)
    testcase.assertNotEqual(extended_data_list[0].data[-1, -1], 0)

def _test_exception_during_view_halts_playback(testcase, hardware_source, exposure):
    enabled = [False]
    def raise_exception():
        if enabled[0]:
            raise Exception("Error during acquisition")
    hardware_source._test_acquire_hook = raise_exception
    hardware_source._test_acquire_exception = lambda *args: None
    hardware_source.start_playing()
    try:
        try:
            hardware_source.get_next_xdatas_to_finish(timeout=10.0)
        finally:
            pass
        testcase.assertTrue(hardware_source.is_playing)
        enabled[0] = True
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            testcase.assertTrue(time.time() - start_time < 3.0)
        testcase.assertFalse(hardware_source.is_playing)
    finally:
        hardware_source.abort_playing(sync_timeout=3.0)

def _test_exception_during_record_halts_playback(testcase, hardware_source, exposure):
    enabled = [False]
    def raise_exception():
        if enabled[0]:
            raise Exception("Error during acquisition")
    hardware_source._test_acquire_hook = raise_exception
    hardware_source._test_acquire_exception = lambda *args: None
    # first make sure that record works as expected
    hardware_source.start_recording()
    try:
        time.sleep(exposure * 0.5)
        testcase.assertTrue(hardware_source.is_recording)
        start = time.time()
        while time.time() - start < exposure * 10.0 and hardware_source.is_recording:
            time.sleep(0.05)
        # print(time.time() - start)
        testcase.assertFalse(hardware_source.is_recording)
    finally:
        hardware_source.abort_recording(sync_timeout=3.0)
    # now raise an exception
    enabled[0] = True
    hardware_source.start_recording()
    try:
        start = time.time()
        while time.time() - start < exposure * 10.0 and hardware_source.is_recording:
            time.sleep(0.05)
        # print(time.time() - start)
        testcase.assertFalse(hardware_source.is_recording)
    finally:
        hardware_source.abort_recording(sync_timeout=3.0)

def _test_able_to_restart_view_after_exception(testcase, hardware_source, exposure):
    enabled = [False]
    def raise_exception():
        if enabled[0]:
            raise Exception("Error during acquisition")
    hardware_source._test_acquire_hook = raise_exception
    hardware_source._test_acquire_exception = lambda *args: None
    hardware_source.start_playing()
    try:
        hardware_source.get_next_xdatas_to_finish(timeout=10.0)
        testcase.assertTrue(hardware_source.is_playing)
        enabled[0] = True
        hardware_source.get_next_xdatas_to_finish(timeout=10.0)
        # avoid a race condition and wait for is_playing to go false.
        start_time = time.time()
        while hardware_source.is_playing:
            time.sleep(0.01)
            testcase.assertTrue(time.time() - start_time < 3.0)
    finally:
        hardware_source.abort_playing(sync_timeout=3.0)
    enabled[0] = False
    hardware_source.start_playing()
    try:
        hardware_source.get_next_xdatas_to_finish(timeout=10.0)
        hardware_source.get_next_xdatas_to_finish(timeout=10.0)
    finally:
        hardware_source.abort_playing(sync_timeout=3.0)

def _test_record_starts_and_finishes_in_reasonable_time(testcase, hardware_source, exposure):
    # a reasonable time is 2x of record mode exposure (record mode exposure is 2x regular exposure)
    hardware_source.start_recording(sync_timeout=3.0)
    try:
        testcase.assertTrue(hardware_source.is_recording)
    except Exception as e:
        hardware_source.abort_recording(sync_timeout=3.0)
    start = time.time()
    hardware_source.stop_recording(sync_timeout=10.0)
    elapsed = time.time() - start
    # print(exposure, elapsed)
    testcase.assertTrue(elapsed < exposure * 8.0)
    testcase.assertFalse(hardware_source.is_recording)


class TestHardwareSourceClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)
        HardwareSource.HardwareSourceManager()._reset()

    def tearDown(self):
        HardwareSource.HardwareSourceManager().close()

    def __acquire_one(self, document_controller, hardware_source):
        hardware_source.start_playing(sync_timeout=3.0)
        hardware_source.stop_playing(sync_timeout=3.0)
        document_controller.periodic()

    def __record_one(self, document_controller, hardware_source):
        hardware_source.start_recording(sync_timeout=3.0)
        document_controller.periodic()

    def __setup_simple_hardware_source(self, persistent_storage_system=None):
        document_model = DocumentModel.DocumentModel(persistent_storage_system=persistent_storage_system)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source = SimpleHardwareSource()
        hardware_source.exposure = 0.01
        HardwareSource.HardwareSourceManager().register_hardware_source(hardware_source)
        return document_controller, document_model, hardware_source

    def __setup_summed_hardware_source(self, persistent_storage_system=None):
        document_model = DocumentModel.DocumentModel(persistent_storage_system=persistent_storage_system)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source = SummedHardwareSource()
        hardware_source.exposure = 0.01
        HardwareSource.HardwareSourceManager().register_hardware_source(hardware_source)
        return document_controller, document_model, hardware_source

    def __setup_line_plot_hardware_source(self, shape, processed=False, persistent_storage_system=None):
        document_model = DocumentModel.DocumentModel(persistent_storage_system=persistent_storage_system)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source = LinePlotHardwareSource(shape, processed)
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
        with contextlib.closing(document_controller):
            _test_acquiring_frames_with_generator_produces_correct_frame_numbers(self, hardware_source, document_controller)

    def test_acquiring_frames_as_partials_with_generator_produces_correct_frame_numbers(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            _test_acquiring_frames_with_generator_produces_correct_frame_numbers(self, hardware_source, document_controller)

    def test_acquire_multiple_frames_reuses_same_data_item(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            _test_acquire_multiple_frames_reuses_same_data_item(self, hardware_source, document_controller)

    def test_acquire_multiple_frames_as_partials_reuses_same_data_item(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            _test_acquire_multiple_frames_reuses_same_data_item(self, hardware_source, document_controller)

    def test_simple_hardware_start_and_stop_actually_stops_acquisition(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            _test_simple_hardware_start_and_stop_actually_stops_acquisition(self, hardware_source, document_controller)

    def test_simple_hardware_start_and_abort_works_as_expected(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            _test_simple_hardware_start_and_abort_works_as_expected(self, hardware_source, document_controller)

    def test_record_only_acquires_one_item(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            _test_record_only_acquires_one_item(self, hardware_source, document_controller)

    def test_record_during_view_records_one_item_and_keeps_viewing(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            _test_record_during_view_records_one_item_and_keeps_viewing(self, hardware_source, document_controller)

    def test_abort_record_during_view_returns_to_view(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            _test_abort_record_during_view_returns_to_view(self, hardware_source, document_controller)

    def test_view_reuses_single_data_item(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            _test_view_reuses_single_data_item(self, hardware_source, document_controller)

    def test_get_next_data_elements_to_finish_returns_full_frames(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            _test_get_next_data_elements_to_finish_returns_full_frames(self, hardware_source, document_controller)

    def test_exception_during_view_halts_playback(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            _test_exception_during_view_halts_playback(self, hardware_source, hardware_source.sleep)

    def test_exception_during_record_halts_playback(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            _test_exception_during_record_halts_playback(self, hardware_source, hardware_source.sleep)

    def test_able_to_restart_view_after_exception(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            _test_able_to_restart_view_after_exception(self, hardware_source, hardware_source.sleep)

    def test_exception_during_view_halts_scan(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            _test_exception_during_view_halts_playback(self, hardware_source, hardware_source.sleep)

    def test_exception_during_record_halts_scan(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            _test_exception_during_record_halts_playback(self, hardware_source, hardware_source.sleep)

    def test_able_to_restart_scan_after_exception_scan(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            _test_able_to_restart_view_after_exception(self, hardware_source, hardware_source.sleep)

    def test_record_starts_and_finishes_in_reasonable_time(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            _test_record_starts_and_finishes_in_reasonable_time(self, hardware_source, hardware_source.sleep)

    def test_view_updates_a_single_data_item_when_multiple_document_controllers_exist(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            document_controller2 = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
            with contextlib.closing(document_controller2):
                self.__acquire_one(document_controller, hardware_source)
                document_controller2.periodic()
                self.__acquire_one(document_controller, hardware_source)
                document_controller2.periodic()
                self.assertEqual(len(document_model.data_items), 1)

    def test_processing_after_acquire_twice_works(self):
        # tests out a problem with 'live' attribute and thumbnails
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            self.__acquire_one(document_controller, hardware_source)
            display_panel.set_display_panel_data_item(document_model.data_items[0])
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            document_model.get_invert_new(document_model.data_items[0])
            document_model.remove_data_item(document_model.data_items[1])
            document_model.data_items[0].set_data(numpy.zeros((4, 4)))

    def test_record_scan_during_view_suspends_the_view(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            # first start playing
            hardware_source.start_playing(sync_timeout=3.0)
            try:
                time.sleep(0.02)  # make the test a little more difficult to pass (this triggered a data item reference problem)
                self.assertFalse(hardware_source.suspended)
                # now start recording
                hardware_source.sleep = 0.06
                hardware_source.start_recording()
                try:
                    hardware_source.suspend_event.wait(3.0)
                    self.assertTrue(hardware_source.suspended)
                    start_time = time.time()
                    while hardware_source.is_recording:
                        time.sleep(0.01)
                        self.assertTrue(time.time() - start_time < 3.0)
                    time.sleep(0.01)
                    self.assertFalse(hardware_source.suspended)
                finally:
                    hardware_source.abort_recording(sync_timeout=3.0)
            finally:
                hardware_source.abort_playing(sync_timeout=3.0)

    def test_view_reuses_externally_configured_item(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source_id = hardware_source.hardware_source_id
            self.assertEqual(len(document_model.data_items), 0)
            data_item = DataItem.DataItem(numpy.ones(256) + 1)
            document_model.append_data_item(data_item)
            document_model.setup_channel(document_model.make_data_item_reference_key(hardware_source_id), data_item)
            # at this point the data item contains 2.0. the acquisition will produce a 1.0.
            # the 2.0 will get copied to data_item 1 and the 1.0 will be replaced into data_item 0.
            new_data_item = copy.deepcopy(document_model.data_items[0])
            document_model.append_data_item(new_data_item)
            self.__acquire_one(document_controller, hardware_source)
            self.assertEqual(len(document_model.data_items), 2)  # old one is copied
            self.assertAlmostEqual(document_model.data_items[0].data[0], 1.0)
            self.assertAlmostEqual(document_model.data_items[1].data[0], 2.0)

    def test_setup_channel_configures_tags_correctly(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source_id = hardware_source.hardware_source_id
            channel_id = "aaa"
            self.assertEqual(len(document_model.data_items), 0)
            data_item = DataItem.DataItem(numpy.ones(256) + 1)
            document_model.append_data_item(data_item)
            data_item_reference_key = document_model.make_data_item_reference_key(hardware_source_id, channel_id)
            document_model.setup_channel(data_item_reference_key, data_item)
            data_item_reference = document_model.get_data_item_reference(data_item_reference_key)
            self.assertEqual(data_item, data_item_reference.data_item)

    def test_partial_acquisition_only_updates_sub_area(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            data = numpy.zeros((256, 256)) + 16
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            document_model.setup_channel(document_model.make_data_item_reference_key(hardware_source.hardware_source_id, "a"), data_item)
            hardware_source.data_channels[0].update(DataAndMetadata.new_data_and_metadata(data), "complete", None, None)
            hardware_source.exposure = 0.02
            hardware_source.start_playing()
            time.sleep(0.01)
            hardware_source.abort_playing(sync_timeout=3.0)
            self.assertEqual(len(document_model.data_items), 1)
            document_controller.periodic()
            data = document_model.data_items[0].data
            self.assertAlmostEqual(data[0, 0], 1.0)
            self.assertAlmostEqual(data[128, 0], 16.0)

    def test_standard_data_element_constructs_metadata_with_hardware_source_as_dict(self):
        data_element = ScanAcquisitionTask(False, 0).make_data_element()
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        self.assertTrue(isinstance(data_item.metadata.get("hardware_source"), dict))

    def test_updating_existing_data_item_updates_creation_even_if_an_updated_date_is_not_supplied(self):
        data_element = ScanAcquisitionTask(False, 0).make_data_element()
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        data_item.created = datetime.datetime(2000, 6, 30)
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        self.assertEqual(data_item.created.year, datetime.datetime.utcnow().year)

    def test_channel_id_and_name_and_index_are_empty_for_simple_hardware_source(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            self.__acquire_one(document_controller, hardware_source)
            data_item0 = document_model.data_items[0]
            hardware_source_metadata = data_item0.metadata.get("hardware_source", dict())
            self.assertEqual(data_item0.title, hardware_source.display_name)
            self.assertEqual(hardware_source_metadata.get("channel_index"), 0)
            self.assertIsNone(hardware_source_metadata.get("channel_id"))
            self.assertIsNone(hardware_source_metadata.get("channel_name"))

    def test_channel_id_and_name_and_index_are_correct_for_view(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            self.__acquire_one(document_controller, hardware_source)
            data_item0 = document_model.data_items[0]
            hardware_source_metadata = data_item0.metadata.get("hardware_source", dict())
            self.assertEqual(data_item0.title, "%s (%s)" % (hardware_source.display_name, "A"))
            self.assertEqual(hardware_source_metadata.get("channel_index"), 0)
            self.assertEqual(hardware_source_metadata.get("channel_id"), "a")
            self.assertEqual(hardware_source_metadata.get("channel_name"), "A")

    def test_channel_id_and_name_and_index_are_correct_for_multiview(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source.channel_enabled_list = (True, True)
            self.__acquire_one(document_controller, hardware_source)
            data_item0 = document_model.data_items[0]
            hardware_source_metadata0 = data_item0.metadata.get("hardware_source", dict())
            self.assertEqual(data_item0.title, "%s (%s)" % (hardware_source.display_name, "A"))
            self.assertEqual(hardware_source_metadata0.get("channel_index"), 0)
            self.assertEqual(hardware_source_metadata0.get("channel_id"), "a")
            self.assertEqual(hardware_source_metadata0.get("channel_name"), "A")
            data_item1 = document_model.data_items[1]
            hardware_source_metadata1 = data_item1.metadata.get("hardware_source", dict())
            self.assertEqual(data_item1.title, "%s (%s)" % (hardware_source.display_name, "B"))
            self.assertEqual(hardware_source_metadata1.get("channel_index"), 1)
            self.assertEqual(hardware_source_metadata1.get("channel_id"), "b")
            self.assertEqual(hardware_source_metadata1.get("channel_name"), "B")

    def test_multiview_reuse_second_channel_by_id_not_index(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source.channel_enabled_list = (True, True)
            self.__acquire_one(document_controller, hardware_source)
            data_item0 = document_model.data_items[0]
            data_item1 = document_model.data_items[1]
            self.assertAlmostEqual(data_item0.data[0, 0], 1.0)  # 1.0 because top half of two part partial acquisition
            self.assertAlmostEqual(data_item1.data[0, 0], 1.0)
            self.assertAlmostEqual(data_item0.data[-1, -1], 2.0)  # 2.0 because bottom half of two part partial acquisition
            self.assertAlmostEqual(data_item1.data[-1, -1], 2.0)
            hardware_source.channel_enabled_list = (False, True)
            self.__acquire_one(document_controller, hardware_source)
            self.assertAlmostEqual(data_item0.data[0, 0], 1.0)
            self.assertAlmostEqual(data_item1.data[0, 0], 3.0)
            self.assertAlmostEqual(data_item0.data[-1, -1], 2.0)
            self.assertAlmostEqual(data_item1.data[-1, -1], 4.0)

    def test_restarting_view_in_same_session_preserves_dependent_data_connections(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            self.__acquire_one(document_controller, hardware_source)
            new_data_item = document_model.get_invert_new(document_model.data_items[0], None)
            document_controller.periodic()
            document_model.recompute_all()
            modified = document_model.data_items[1].modified
            value = document_model.data_items[1].data[0]
            acq_value = document_model.data_items[0].data[0]
            self.assertEqual(acq_value, 1.0)
            self.assertEqual(value, -acq_value)
            self.__acquire_one(document_controller, hardware_source)
            document_controller.periodic()
            document_model.recompute_all()
            self.assertNotEqual(modified, document_model.data_items[1].modified)
            value = document_model.data_items[1].data[0]
            acq_value = document_model.data_items[0].data[0]
            self.assertEqual(acq_value, 2.0)
            self.assertEqual(value, -acq_value)

    def test_restarting_view_after_reload_preserves_dependent_data_connections(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            self.__acquire_one(document_controller, hardware_source)
            new_data_item = document_model.get_invert_new(document_model.data_items[0], None)
            document_controller.periodic()
            document_model.recompute_all()
            document_model.start_new_session()
            new_data_item = copy.deepcopy(document_model.data_items[0])
            document_model.append_data_item(new_data_item)
            self.__acquire_one(document_controller, hardware_source)
            document_controller.periodic()
            document_model.recompute_all()
            self.assertEqual(len(document_model.data_items), 3)
            value = document_model.data_items[1].data[0]
            acq_value0 = document_model.data_items[0].data[0]
            acq_value2 = document_model.data_items[2].data[0]
            self.assertEqual(acq_value0, 2.0)
            self.assertEqual(acq_value2, 1.0)
            self.assertEqual(value, -acq_value0)

    def test_reloading_restarted_view_after_size_change_produces_data_item_with_unique_uuid(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_controller):
            document_model.session_id = "20000630-150200"
            self.__acquire_one(document_controller, hardware_source)
            self.assertEqual(len(document_model.data_items), 1)
            new_data_item = copy.deepcopy(document_model.data_items[0])
            document_model.append_data_item(new_data_item)
            document_model.session_id = "20000630-150201"
            self.__acquire_one(document_controller, hardware_source)
            self.assertEqual(len(document_model.data_items), 2)
        # reload
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            self.assertEqual(len(document_model.data_items), len(set([d.uuid for d in document_model.data_items])))
            self.assertEqual(len(document_model.data_items), 2)

    def test_single_frame_acquisition_generates_single_canvas_repaint_event_for_image(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source.image = numpy.ones((4, 4))
            display_panel = document_controller.selected_display_panel
            self.__acquire_one(document_controller, hardware_source)
            display_panel.set_display_panel_data_item(document_model.data_items[0])
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            repaint_count = display_panel.display_canvas_item._repaint_count
            self.__acquire_one(document_controller, hardware_source)
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            self.assertEqual(display_panel.display_canvas_item._repaint_count, repaint_count + 1)

    def test_single_frame_acquisition_generates_single_canvas_update_event_for_image(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source.image = numpy.ones((4, 4))
            display_panel = document_controller.selected_display_panel
            self.__acquire_one(document_controller, hardware_source)
            display_panel.set_display_panel_data_item(document_model.data_items[0])
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            self.__acquire_one(document_controller, hardware_source)
            update_count = display_panel.display_canvas_item._update_count
            self.__acquire_one(document_controller, hardware_source)
            self.__acquire_one(document_controller, hardware_source)
            new_update_count = display_panel.display_canvas_item._update_count
            self.assertEqual(new_update_count, update_count + 2)

    def test_partial_frame_acquisition_generates_single_canvas_update_event_for_each_segment(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source.image = numpy.ones((4, 4))
            display_panel = document_controller.selected_display_panel
            self.__acquire_one(document_controller, hardware_source)
            display_panel.set_display_panel_data_item(document_model.data_items[0])
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            repaint_count = display_panel.display_canvas_item._repaint_count
            hardware_source.sleep = 0.03  # each partial will sleep for this long
            hardware_source.start_playing(sync_timeout=3.0)
            time.sleep(0.05)  # make sure we're in the 2nd partial
            document_controller.periodic()
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            hardware_source.stop_playing(sync_timeout=3.0)
            document_controller.periodic()
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            self.assertEqual(display_panel.display_canvas_item._repaint_count, repaint_count + 2)

    def test_single_frame_acquisition_generates_single_canvas_update_event_for_line_plot(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source.image = numpy.ones((4, ))
            display_panel = document_controller.selected_display_panel
            self.__acquire_one(document_controller, hardware_source)
            display_panel.set_display_panel_data_item(document_model.data_items[0])
            repaint_count = display_panel.display_canvas_item._repaint_count
            self.__acquire_one(document_controller, hardware_source)
            display_panel.root_container.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))
            self.assertEqual(display_panel.display_canvas_item._repaint_count, repaint_count + 1)

    def test_partial_frame_acquisition_avoids_unnecessary_merges(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source.image = numpy.ones((4, 4))
            display_panel = document_controller.selected_display_panel
            self.__acquire_one(document_controller, hardware_source)
            display_panel.set_display_panel_data_item(document_model.data_items[0])
            document_controller.periodic()
            self.assertEqual(document_model._get_pending_data_item_updates_count(), 0)
            hardware_source.start_playing(sync_timeout=3.0)
            hardware_source.stop_playing(sync_timeout=3.0)
            hardware_source.start_playing(sync_timeout=3.0)
            hardware_source.stop_playing(sync_timeout=3.0)
            self.assertEqual(document_model._get_pending_data_item_updates_count(), 1)

    def test_two_acquisitions_succeed(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            self.__acquire_one(document_controller, hardware_source)
            self.__acquire_one(document_controller, hardware_source)

    def test_two_scan_acquisitions_succeed(self):
        document_controller, document_model, hardware_source = self.__setup_scan_hardware_source()
        with contextlib.closing(document_controller):
            self.__acquire_one(document_controller, hardware_source)
            self.__acquire_one(document_controller, hardware_source)

    def test_deleting_data_item_during_acquisition_recovers_correctly(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source.start_playing()
            start_time = time.time()
            while not hardware_source.is_playing:
                time.sleep(0.01)
                self.assertTrue(time.time() - start_time < 3.0)
            start_time = time.time()
            while len(document_model.data_items) == 0:
                time.sleep(0.01)
                document_controller.periodic()
                self.assertTrue(time.time() - start_time < 3.0)
            document_model.remove_data_item(document_model.data_items[0])
            start_time = time.time()
            while len(document_model.data_items) == 0:
                time.sleep(0.01)
                document_controller.periodic()
                self.assertTrue(time.time() - start_time < 3.0)
            hardware_source.abort_playing(sync_timeout=3.0)
            document_controller.periodic()

    def test_data_generator_generates_ndarrays(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source.start_playing()
            try:
                with HardwareSource.get_data_generator_by_id(hardware_source.hardware_source_id) as data_generator:
                    self.assertIsInstance(data_generator(), numpy.ndarray)
                    self.assertIsInstance(data_generator(), numpy.ndarray)
            finally:
                hardware_source.abort_playing(sync_timeout=3.0)

    def test_hardware_source_api_data_item_setup(self):
        document_controller, document_model, _hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            library = Facade.Library(document_model)  # hack to build Facade.Library directly
            hardware_source = Facade.HardwareSource(_hardware_source)
            self.assertIsNone(library.get_data_item_for_hardware_source(hardware_source))
            data_item = library.get_data_item_for_hardware_source(hardware_source, create_if_needed=True)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(document_model.data_items[0], data_item._data_item)
            self.assertIsNone(document_model.data_items[0].data)

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

            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(document_model.data_items[0], data_item._data_item)
            self.assertIsNotNone(document_model.data_items[0].data)

    def test_hardware_source_grabs_data_with_correct_descriptor(self):
        document_controller, document_model, hardware_source = self.__setup_line_plot_hardware_source((16, 2))
        with contextlib.closing(document_controller):
            self.__acquire_one(document_controller, hardware_source)
            xdata = document_model.data_items[0].xdata
            self.assertEqual(len(xdata.dimensional_shape), 2)
            self.assertEqual(xdata.collection_dimension_count, 1)
            self.assertEqual(xdata.datum_dimension_count, 1)

    def test_hardware_source_grabs_summed_1d_data(self):
        # really an error case, 1d acquisition + summed processing
        document_controller, document_model, hardware_source = self.__setup_line_plot_hardware_source((16, ), processed=True)
        with contextlib.closing(document_controller):
            self.__acquire_one(document_controller, hardware_source)
            xdata = document_model.data_items[0].xdata
            self.assertEqual(len(xdata.dimensional_shape), 1)
            self.assertEqual(xdata.datum_dimension_count, 1)
            xdata = document_model.data_items[1].xdata
            self.assertEqual(len(xdata.dimensional_shape), 1)
            self.assertEqual(xdata.datum_dimension_count, 1)

    def test_hardware_source_grabs_summed_1xn_data(self):
        # really an error case, 1d acquisition + summed processing
        document_controller, document_model, hardware_source = self.__setup_line_plot_hardware_source((1, 16), processed=True)
        with contextlib.closing(document_controller):
            self.__acquire_one(document_controller, hardware_source)
            xdata = document_model.data_items[0].xdata
            self.assertEqual(len(xdata.dimensional_shape), 2)
            self.assertEqual(xdata.datum_dimension_count, 1)
            xdata = document_model.data_items[1].xdata
            self.assertEqual(len(xdata.dimensional_shape), 1)
            self.assertEqual(xdata.datum_dimension_count, 1)

    def test_hardware_source_api_grabs_summed_data(self):
        document_controller, document_model, _hardware_source = self.__setup_summed_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source = Facade.HardwareSource(_hardware_source)
            hardware_source.start_playing()
            try:
                xdata_list = hardware_source.grab_next_to_finish()
                self.assertEqual(len(xdata_list), 2)
                self.assertEqual(len(xdata_list[0].dimensional_shape), 2)
                self.assertEqual(len(xdata_list[1].dimensional_shape), 1)
            finally:
                hardware_source.abort_playing()

    def test_hardware_source_api_records_on_thread(self):
        document_controller, document_model, _hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            hardware_source = Facade.HardwareSource(_hardware_source)
            done_event = threading.Event()
            def do_record():
                try:
                    xdata_list = hardware_source.record()
                    self.assertEqual(len(xdata_list), 1)
                    xdata_list = hardware_source.record()
                    self.assertEqual(len(xdata_list), 1)
                finally:
                    done_event.set()
            threading.Thread(target=do_record).start()
            done_event.wait(3.0)

    def test_hardware_source_updates_timezone_during_acquisition(self):
        document_controller, document_model, hardware_source = self.__setup_simple_hardware_source()
        with contextlib.closing(document_controller):
            try:
                hardware_source_id = hardware_source.hardware_source_id
                Utility.local_timezone_override = [None]
                Utility.local_utcoffset_override = [0]
                data_item = DataItem.DataItem(numpy.ones(256) + 1)
                self.assertIsNone(data_item.timezone)
                self.assertEqual(data_item.timezone_offset, "+0000")
                document_model.append_data_item(data_item)
                document_model.setup_channel(document_model.make_data_item_reference_key(hardware_source_id), data_item)
                Utility.local_timezone_override = ["Europe/Athens"]
                Utility.local_utcoffset_override = [180]
                self.__acquire_one(document_controller, hardware_source)
                self.assertEqual(data_item.timezone, "Europe/Athens")
                self.assertEqual(data_item.timezone_offset, "+0300")
            finally:
                Utility.local_timezone_override = None
                Utility.local_utcoffset_override = None


if __name__ == '__main__':
    unittest.main()
