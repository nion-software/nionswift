# standard libraries
import pathlib
import tempfile
import threading
import time
import typing
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Facade
from nion.swift import ScriptsDialog
from nion.swift.model import DataItem
from nion.swift.test import TestContext
from nion.ui import UserInterface


Facade.initialize()


class TestScriptsDialogClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup(set_global=True)
        self._test_setup.app.workspace_dir = str()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_interactive_script_can_read_display_xdata(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            document_controller.document_model.append_data_item(DataItem.DataItem(numpy.ones((4, 6))))
            results = list()

            # an interactive script runs on its own thread and the API queues each call to the main thread.
            def script() -> None:
                api = ScriptsDialog.InteractiveScriptAPIBroker(None).get_api("~1.0")
                results.append(api.library.data_items[0].display.xdata.data_shape)

            script_thread = threading.Thread(target=script, daemon=True)
            script_thread.start()
            start_time = time.time()
            while script_thread.is_alive() and time.time() - start_time < 10.0:
                document_controller.periodic()
                time.sleep(0.01)
            self.assertEqual([(4, 6)], results)

    def test_interactive_script_setting_data_through_data_ref_changes_data_on_main_thread(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4, 6)))
            document_model.append_data_item(data_item)

            # listeners such as display updates expect data changes on the main thread.
            data_changed_threads = list()
            data_changed_listener = data_item.data_changed_event.listen(lambda: data_changed_threads.append(threading.current_thread()))

            # an interactive script runs on its own thread and the API queues each call to the main thread.
            def script() -> None:
                api = ScriptsDialog.InteractiveScriptAPIBroker(None).get_api("~1.0")
                with api.library.data_ref_for_data_item(api.library.data_items[0]) as data_ref:
                    data_ref.data = numpy.ones((4, 6))

            script_thread = threading.Thread(target=script, daemon=True)
            script_thread.start()
            start_time = time.time()
            while script_thread.is_alive() and time.time() - start_time < 10.0:
                document_controller.periodic()
                time.sleep(0.01)
            self.assertTrue(numpy.array_equal(numpy.ones((4, 6)), data_item.data))
            self.assertTrue(data_changed_threads)
            self.assertEqual({threading.main_thread()}, set(data_changed_threads))

    def test_script_print_breaks_lines_like_built_in_print(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            script_path = pathlib.Path(directory_str) / "print_script.py"
            script_path.write_text("print(\"x\", end=\"\")\nprint(\"y\")\nprint()\nprint(\"z\")\n")
            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            try:
                output_widget = typing.cast(UserInterface.TextEditWidget, dialog.content.find_widget_by_id("output"))
                dialog.run_script(str(script_path))
                expected_text = "xy\n\nz"
                start_time = time.time()
                while output_widget.text != expected_text and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                self.assertEqual(expected_text, output_widget.text)
            finally:
                dialog.close()

    def test_script_output_written_to_stdout_keeps_its_line_breaks(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            script_path = pathlib.Path(directory_str) / "stdout_script.py"
            script_path.write_text("import sys\nsys.stdout.write(\"x\")\nsys.stdout.write(\"y\\n\")\nsys.stdout.write(\"z\\n\")\n")
            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            try:
                output_widget = typing.cast(UserInterface.TextEditWidget, dialog.content.find_widget_by_id("output"))
                dialog.run_script(str(script_path))
                expected_text = "xy\nz"
                start_time = time.time()
                while output_widget.text != expected_text and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                self.assertEqual(expected_text, output_widget.text)
            finally:
                dialog.close()


if __name__ == '__main__':
    unittest.main()
