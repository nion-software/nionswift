# standard libraries
import pathlib
import sys
import tempfile
import textwrap
import threading
import time
import types
import typing
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import ConsoleDialog
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

    def test_script_started_from_console_shows_output_written_to_stdout(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            directory = pathlib.Path(directory_str)
            started_path = directory / "started"
            continue_path = directory / "continue"
            script_path = directory / "stdout_script.py"
            # the script writes only after the console command has returned, which is when the console stops capturing output.
            script_path.write_text(f"import pathlib, sys, time\n"
                                   f"pathlib.Path({str(started_path)!r}).touch()\n"
                                   f"start_time = time.time()\n"
                                   f"while not pathlib.Path({str(continue_path)!r}).exists() and time.time() - start_time < 10.0:\n"
                                   f"    time.sleep(0.01)\n"
                                   f"sys.stdout.write(\"x\\n\")\n")

            def wait_until_script_started() -> None:
                start_time = time.time()
                while not started_path.exists() and time.time() - start_time < 10.0:
                    time.sleep(0.01)

            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            console = ConsoleDialog.ConsoleWidgetStateController({"dialog": dialog, "wait_until_script_started": wait_until_script_started})
            try:
                output_widget = typing.cast(UserInterface.TextEditWidget, dialog.content.find_widget_by_id("output"))
                console.interpret_command(f"dialog.run_script({str(script_path)!r}); wait_until_script_started()")
                continue_path.touch()
                start_time = time.time()
                while output_widget.text != "x" and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                self.assertEqual("x", output_widget.text)
            finally:
                dialog.close()
                console.close()

    def test_script_started_from_console_leaves_stdout_and_stderr_as_they_were(self):
        # the streams are restored only once every redirection has ended, so this also fails when an earlier test leaves
        # a redirection which has not ended.
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            directory = pathlib.Path(directory_str)
            started_path = directory / "started"
            continue_path = directory / "continue"
            script_path = directory / "stdout_script.py"
            # the script runs on past the end of the console command, so that the two redirections overlap.
            script_path.write_text(f"import pathlib, sys, time\n"
                                   f"pathlib.Path({str(started_path)!r}).touch()\n"
                                   f"start_time = time.time()\n"
                                   f"while not pathlib.Path({str(continue_path)!r}).exists() and time.time() - start_time < 10.0:\n"
                                   f"    time.sleep(0.01)\n"
                                   f"sys.stdout.write(\"x\\n\")\n")

            def wait_until_script_started() -> None:
                start_time = time.time()
                while not started_path.exists() and time.time() - start_time < 10.0:
                    time.sleep(0.01)

            stdout, stderr = sys.stdout, sys.stderr
            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            console = ConsoleDialog.ConsoleWidgetStateController({"dialog": dialog, "wait_until_script_started": wait_until_script_started})
            try:
                output_widget = typing.cast(UserInterface.TextEditWidget, dialog.content.find_widget_by_id("output"))
                console.interpret_command(f"dialog.run_script({str(script_path)!r}); wait_until_script_started()")
                continue_path.touch()
                start_time = time.time()
                while output_widget.text != "x" and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
            finally:
                dialog.close()
                console.close()
            self.assertIs(stdout, sys.stdout)
            self.assertIs(stderr, sys.stderr)

    def test_script_shows_output_written_to_stdout_by_thread_started_with_its_context(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            script_path = pathlib.Path(directory_str) / "thread_script.py"
            script_path.write_text("import contextvars, sys, threading\n"
                                   "thread = threading.Thread(target=contextvars.copy_context().run, args=(sys.stdout.write, \"x\\n\"))\n"
                                   "thread.start()\n"
                                   "thread.join()\n")
            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            try:
                output_widget = typing.cast(UserInterface.TextEditWidget, dialog.content.find_widget_by_id("output"))
                dialog.run_script(str(script_path))
                start_time = time.time()
                while output_widget.text != "x" and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                self.assertEqual("x", output_widget.text)
            finally:
                dialog.close()

    def test_output_panel_shows_output_written_outside_a_running_script_and_not_the_script_output(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            output_panel = document_controller.find_dock_panel("output-panel")
            assert output_panel
            output_panel_widget = typing.cast(UserInterface.TextEditWidget, output_panel.widget)
            directory = pathlib.Path(directory_str)
            started_path = directory / "started"
            continue_path = directory / "continue"
            script_path = directory / "stdout_script.py"
            # the script writes while the main thread writes outside it.
            script_path.write_text(f"import pathlib, sys, time\n"
                                   f"sys.stdout.write(\"written by the script\\n\")\n"
                                   f"pathlib.Path({str(started_path)!r}).touch()\n"
                                   f"start_time = time.time()\n"
                                   f"while not pathlib.Path({str(continue_path)!r}).exists() and time.time() - start_time < 10.0:\n"
                                   f"    time.sleep(0.01)\n")
            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            try:
                output_widget = typing.cast(UserInterface.TextEditWidget, dialog.content.find_widget_by_id("output"))
                dialog.run_script(str(script_path))
                start_time = time.time()
                while not started_path.exists() and time.time() - start_time < 10.0:
                    time.sleep(0.01)
                print("printed outside the script")
                sys.stderr.write("written to stderr outside the script\n")
                continue_path.touch()
                start_time = time.time()
                while output_widget.text != "written by the script" and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                document_controller.periodic()
                output_panel_text = output_panel_widget.text or str()
                self.assertEqual("written by the script", output_widget.text)
                self.assertIn("printed outside the script", output_panel_text)
                self.assertIn("written to stderr outside the script", output_panel_text)
                self.assertNotIn("written by the script", output_panel_text)
            finally:
                dialog.close()

    def test_script_calling_run_script_through_its_api_shows_the_output_of_the_script_it_runs(self):
        with TestContext.MemoryProfileContext() as profile_context, tempfile.TemporaryDirectory() as directory_str:
            # the API given to the script queues each call to the application's window.
            app = self._test_setup.app
            document_model = profile_context.create_document_model(auto_close=False)
            app._set_profile_for_test(profile_context.profile)
            document_controller = app.create_document_controller(document_model, "library")
            directory = pathlib.Path(directory_str)
            inner_script_path = directory / "inner_script.py"
            inner_script_path.write_text("import sys\nsys.stdout.write(\"written by the inner script\\n\")\n")
            script_path = directory / "outer_script.py"
            script_path.write_text(f"def script_main(api_broker):\n"
                                   f"    api_broker.get_api(\"~1.0\").run_script(file_path={str(inner_script_path)!r})\n")
            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            try:
                output_widget = typing.cast(UserInterface.TextEditWidget, dialog.content.find_widget_by_id("output"))
                dialog.run_script(str(script_path))
                start_time = time.time()
                while output_widget.text != "written by the inner script" and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                self.assertEqual("written by the inner script", output_widget.text)
            finally:
                dialog.close()
                document_controller.close()
                app._set_profile_for_test(None)

    def test_script_shows_output_written_to_stdout_by_its_thread_after_the_script_finishes(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            directory = pathlib.Path(directory_str)
            continue_path = directory / "continue"
            script_path = directory / "thread_script.py"
            script_path.write_text(f"import contextvars, pathlib, sys, threading, time\n"
                                   f"def write_later():\n"
                                   f"    start_time = time.time()\n"
                                   f"    while not pathlib.Path({str(continue_path)!r}).exists() and time.time() - start_time < 10.0:\n"
                                   f"        time.sleep(0.01)\n"
                                   f"    sys.stdout.write(\"x\\n\")\n"
                                   f"threading.Thread(target=contextvars.copy_context().run, args=(write_later,), daemon=True).start()\n")

            # the dialog shows a Finished label once the script returns.
            def is_finished() -> bool:
                widgets: list[UserInterface.Widget] = [dialog.content]
                while widgets:
                    widget = widgets.pop()
                    if isinstance(widget, UserInterface.LabelWidget) and widget.text == "Finished":
                        return True
                    widgets.extend(widget._contained_widgets)
                return False

            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            try:
                output_widget = typing.cast(UserInterface.TextEditWidget, dialog.content.find_widget_by_id("output"))
                dialog.run_script(str(script_path))
                start_time = time.time()
                while not is_finished() and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                continue_path.touch()
                start_time = time.time()
                while output_widget.text != "x" and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                self.assertEqual("x", output_widget.text)
            finally:
                dialog.close()

    def test_script_run_again_does_not_show_output_of_a_thread_of_the_earlier_run(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            directory = pathlib.Path(directory_str)
            first_run_path = directory / "first_run"
            continue_path = directory / "continue"
            written_path = directory / "written"
            script_path = directory / "thread_script.py"
            # the first run starts a thread which writes during the second run. the second run writes on its own.
            script_path.write_text(f"import contextvars, pathlib, sys, threading, time\n"
                                   f"def write_later():\n"
                                   f"    start_time = time.time()\n"
                                   f"    while not pathlib.Path({str(continue_path)!r}).exists() and time.time() - start_time < 10.0:\n"
                                   f"        time.sleep(0.01)\n"
                                   f"    print(\"printed by the first run\")\n"
                                   f"    sys.stdout.write(\"written by the first run\\n\")\n"
                                   f"    pathlib.Path({str(written_path)!r}).touch()\n"
                                   f"if not pathlib.Path({str(first_run_path)!r}).exists():\n"
                                   f"    pathlib.Path({str(first_run_path)!r}).touch()\n"
                                   f"    threading.Thread(target=contextvars.copy_context().run, args=(write_later,), daemon=True).start()\n"
                                   f"else:\n"
                                   f"    sys.stdout.write(\"second\\n\")\n")

            # the dialog shows a Run Again button once the script returns.
            def find_run_again_button() -> UserInterface.PushButtonWidget | None:
                widgets: list[UserInterface.Widget] = [dialog.content]
                while widgets:
                    widget = widgets.pop()
                    if isinstance(widget, UserInterface.PushButtonWidget) and widget.text == "Run Again":
                        return widget
                    widgets.extend(widget._contained_widgets)
                return None

            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            try:
                output_widget = typing.cast(UserInterface.TextEditWidget, dialog.content.find_widget_by_id("output"))
                dialog.run_script(str(script_path))
                start_time = time.time()
                while not (run_again_button := find_run_again_button()) and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                assert run_again_button and run_again_button.on_clicked
                run_again_button.on_clicked()
                start_time = time.time()
                while output_widget.text != "second" and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                continue_path.touch()
                start_time = time.time()
                while not written_path.exists() and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
                document_controller.periodic()
                self.assertEqual("second", output_widget.text)
            finally:
                dialog.close()

    def test_script_thread_output_after_the_dialog_closes_goes_to_the_output_panel(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            output_panel = document_controller.find_dock_panel("output-panel")
            assert output_panel
            output_panel_widget = typing.cast(UserInterface.TextEditWidget, output_panel.widget)
            directory = pathlib.Path(directory_str)
            continue_path = directory / "continue"
            written_path = directory / "written"
            script_path = directory / "thread_script.py"
            script_path.write_text(f"import contextvars, pathlib, sys, threading, time\n"
                                   f"def write_later():\n"
                                   f"    start_time = time.time()\n"
                                   f"    while not pathlib.Path({str(continue_path)!r}).exists() and time.time() - start_time < 10.0:\n"
                                   f"        time.sleep(0.01)\n"
                                   f"    print(\"printed after the dialog closed\")\n"
                                   f"    sys.stdout.write(\"written after the dialog closed\\n\")\n"
                                   f"    pathlib.Path({str(written_path)!r}).touch()\n"
                                   f"threading.Thread(target=contextvars.copy_context().run, args=(write_later,), daemon=True).start()\n")

            # the dialog shows a Finished label once the script returns.
            def is_finished() -> bool:
                widgets: list[UserInterface.Widget] = [dialog.content]
                while widgets:
                    widget = widgets.pop()
                    if isinstance(widget, UserInterface.LabelWidget) and widget.text == "Finished":
                        return True
                    widgets.extend(widget._contained_widgets)
                return False

            dialog = ScriptsDialog.RunScriptDialog(document_controller)
            try:
                dialog.run_script(str(script_path))
                start_time = time.time()
                while not is_finished() and time.time() - start_time < 10.0:
                    document_controller.periodic()
                    time.sleep(0.01)
            finally:
                dialog.close()
            continue_path.touch()
            start_time = time.time()
            while not written_path.exists() and time.time() - start_time < 10.0:
                time.sleep(0.01)
            document_controller.periodic()
            output_panel_text = output_panel_widget.text or str()
            self.assertIn("printed after the dialog closed", output_panel_text)
            self.assertIn("written after the dialog closed", output_panel_text)

    def test_script_thread_printing_to_the_dialog_after_it_closes_prints_to_the_output_panel(self):
        # the script starts a thread which outlives it and prints through the dialog only after the dialog has closed.
        script = textwrap.dedent("""
            import threading
            import scripts_dialog_test_support as support

            def script_main(api_broker):
                interactive = api_broker.get_interactive(version="~1.0")

                def print_after_close():
                    support.dialog_closed.wait(10.0)
                    interactive.print("printed after the dialog closed")
                    support.finished.set()

                threading.Thread(target=print_after_close, daemon=True).start()
            """)
        support = types.ModuleType("scripts_dialog_test_support")
        support.dialog_closed = threading.Event()
        support.finished = threading.Event()
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            output_panel = document_controller.find_dock_panel("output-panel")
            assert output_panel
            output_panel_widget = typing.cast(UserInterface.TextEditWidget, output_panel.widget)
            sys.modules[support.__name__] = support
            try:
                script_path = pathlib.Path(directory_str) / "print_after_close.py"
                script_path.write_text(script)
                dialog = ScriptsDialog.RunScriptDialog(document_controller)
                try:
                    dialog.run_script(str(script_path))
                finally:
                    dialog.close()
                support.dialog_closed.set()
                start_time = time.time()
                while not support.finished.is_set() and time.time() - start_time < 10.0:
                    time.sleep(0.01)
                document_controller.periodic()
                self.assertIn("printed after the dialog closed", output_panel_widget.text or str())
            finally:
                support.dialog_closed.set()
                del sys.modules[support.__name__]


if __name__ == '__main__':
    unittest.main()
