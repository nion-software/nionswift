# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import Facade
from nion.swift import RecorderPanel
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.ui import TestUI


Facade.initialize()

class TestRecorderPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_recorder_records_live_data(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            recorder = RecorderPanel.Recorder(document_controller, data_item)
            with contextlib.closing(recorder):
                with document_model.data_item_live(data_item):
                    count = 4
                    recorder.start_recording(10, 1, count)
                    for i in range(count):
                        recorder.continue_recording(10 + i + 0.25)
                        recorder.continue_recording(10 + i + 0.75)
                        data_item.set_data(data_item.data + 1)
            self.assertEqual(2, len(document_model.data_items))
            recorded_data_item = document_model.data_items[1]
            self.assertTrue(recorded_data_item.xdata.is_sequence)
            self.assertEqual((4, 8, 8), recorded_data_item.xdata.dimensional_shape)

    def test_recorder_puts_recorded_data_item_under_transaction(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            recorder = RecorderPanel.Recorder(document_controller, data_item)
            with contextlib.closing(recorder):
                with document_model.data_item_live(data_item):
                    count = 4
                    recorder.start_recording(10, 1, count)
                    for i in range(count):
                        recorder.continue_recording(10 + i + 0.25)
                        data_item.set_data(data_item.data + 1)
                        if i != count - 1:  # last iteration it should fall out of transaction state since it is finished
                            self.assertTrue(document_model.data_items[1].in_transaction_state)
                        else:
                            self.assertFalse(document_model.data_items[1].in_transaction_state)
            self.assertFalse(document_model.data_items[1].in_transaction_state)

    def test_recorder_state_is_reported_properly(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            recorder_state_ref = ["unknown"]
            def recorder_state_changed(recorder_state): recorder_state_ref[0] = recorder_state
            recorder = RecorderPanel.Recorder(document_controller, data_item)
            recorder.on_recording_state_changed = recorder_state_changed
            with contextlib.closing(recorder):
                with document_model.data_item_live(data_item):
                    count = 4
                    recorder.start_recording(10, 1, count)
                    for i in range(count):
                        recorder.continue_recording(10 + i + 0.25)
                        data_item.set_data(data_item.data + 1)
                        if i != count - 1:  # last iteration it should fall out of transaction state since it is finished
                            self.assertEqual(recorder_state_ref[0], "recording")
                        else:
                            self.assertEqual(recorder_state_ref[0], "stopped")
                self.assertEqual(recorder_state_ref[0], "stopped")
