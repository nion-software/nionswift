# standard libraries
import io
import logging
import pathlib
import sys
import tempfile
import threading
import time
import typing
import unittest

# local libraries
from nion.swift import ConsoleDialog
from nion.swift import Facade
from nion.swift.test import TestContext
from nion.ui import UserInterface


Facade.initialize()


class TestConsoleDialogClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup(set_global=True)

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_console_command_result_is_what_the_command_prints(self):
        console = ConsoleDialog.ConsoleWidgetStateController(dict())
        try:
            self.assertEqual(("1\n", 0), console.interpret_command("print(1)"))
        finally:
            console.close()

    def test_console_command_which_raises_returns_its_traceback_as_an_error(self):
        console = ConsoleDialog.ConsoleWidgetStateController(dict())
        try:
            result, error_code = console.interpret_command("1 / 0")
            self.assertEqual(-1, error_code)
            self.assertIn("ZeroDivisionError", result)
        finally:
            console.close()

    def test_console_command_leaves_stdout_and_stderr_as_they_were(self):
        stdout, stderr = sys.stdout, sys.stderr
        console = ConsoleDialog.ConsoleWidgetStateController(dict())
        try:
            console.interpret_command("print(1)")
            self.assertIs(stdout, sys.stdout)
            self.assertIs(stderr, sys.stderr)
        finally:
            console.close()

    def test_console_command_result_leaves_out_output_of_a_thread_started_without_a_copy_of_the_context(self):
        # the thread stands in for other work writing while the command runs, such as a running script.
        def write_on_another_thread() -> None:
            thread = threading.Thread(target=sys.stdout.write, args=("y\n",))
            thread.start()
            thread.join()

        stdout = sys.stdout
        console = ConsoleDialog.ConsoleWidgetStateController({"write_on_another_thread": write_on_another_thread})
        try:
            # stands in for the Output panel, which receives the thread's output.
            sys.stdout = io.StringIO()
            self.assertEqual(("", 0), console.interpret_command("write_on_another_thread()"))
        finally:
            sys.stdout = stdout
            console.close()

    def test_console_run_script_shows_output_of_a_thread_before_output_the_script_writes_after_joining_it(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            script_path = pathlib.Path(directory_str) / "thread_script.py"
            script_path.write_text("import threading\n"
                                   "thread = threading.Thread(target=print, args=(\"written from a thread\",))\n"
                                   "thread.start()\n"
                                   "thread.join()\n"
                                   "print(\"written from the script\")\n")
            console_widget = ConsoleDialog.ConsoleWidget(document_controller.ui, logging.getLogger("console_test"), {"api": Facade.get_api("~1.0", "~1.0")})
            try:
                # the run_script the console defines at startup.
                console_widget.interpret_lines(["def run_script(*args, **kwargs):", "  api.run_script(*args, stdout=_stdout, **kwargs)", ""])
                console_widget.insert_lines([f"run_script(file_path={str(script_path)!r})"])
                console_text = typing.cast(UserInterface.TextEditWidget, console_widget.content_widget.children[0]).text or str()
                self.assertIn("written from a thread", console_text)
                self.assertIn("written from the script", console_text)
                self.assertLess(console_text.index("written from a thread"), console_text.index("written from the script"))
            finally:
                console_widget.close()

    def test_console_run_script_sends_output_of_a_thread_after_the_command_returns_to_stdout(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            directory = pathlib.Path(directory_str)
            continue_path = directory / "continue"
            written_path = directory / "written"
            script_path = directory / "thread_script.py"
            script_path.write_text(f"import pathlib, threading, time\n"
                                   f"def write_later():\n"
                                   f"    start_time = time.time()\n"
                                   f"    while not pathlib.Path({str(continue_path)!r}).exists() and time.time() - start_time < 10.0:\n"
                                   f"        time.sleep(0.01)\n"
                                   f"    print(\"written after the command returned\")\n"
                                   f"    pathlib.Path({str(written_path)!r}).touch()\n"
                                   f"threading.Thread(target=write_later, daemon=True).start()\n")
            stdout = sys.stdout
            console_widget = ConsoleDialog.ConsoleWidget(document_controller.ui, logging.getLogger("console_test"), {"api": Facade.get_api("~1.0", "~1.0")})
            try:
                # stands in for the Output panel, which receives output after the command which wrote it returns.
                sys.stdout = io.StringIO()
                # the run_script the console defines at startup.
                console_widget.interpret_lines(["def run_script(*args, **kwargs):", "  api.run_script(*args, stdout=_stdout, **kwargs)", ""])
                console_widget.insert_lines([f"run_script(file_path={str(script_path)!r})"])
                continue_path.touch()
                start_time = time.time()
                while not written_path.exists() and time.time() - start_time < 10.0:
                    time.sleep(0.01)
                self.assertIn("written after the command returned", sys.stdout.getvalue())
            finally:
                # release the thread in any case, so that it finishes with the test.
                continue_path.touch()
                sys.stdout = stdout
                console_widget.close()

    def test_console_run_script_called_on_a_thread_sends_its_output_after_the_command_returns_to_stdout(self):
        with TestContext.create_memory_context() as test_context, tempfile.TemporaryDirectory() as directory_str:
            document_controller = test_context.create_document_controller()
            directory = pathlib.Path(directory_str)
            continue_path = directory / "continue"
            written_path = directory / "written"
            script_path = directory / "late_script.py"
            script_path.write_text(f"import pathlib, time\n"
                                   f"start_time = time.time()\n"
                                   f"while not pathlib.Path({str(continue_path)!r}).exists() and time.time() - start_time < 10.0:\n"
                                   f"    time.sleep(0.01)\n"
                                   f"print(\"written after the command returned\")\n"
                                   f"pathlib.Path({str(written_path)!r}).touch()\n")
            stdout = sys.stdout
            console_widget = ConsoleDialog.ConsoleWidget(document_controller.ui, logging.getLogger("console_test"), {"api": Facade.get_api("~1.0", "~1.0")})
            try:
                # stands in for the Output panel, which receives output after the command which wrote it returns.
                sys.stdout = io.StringIO()
                # the run_script the console defines at startup.
                console_widget.interpret_lines(["def run_script(*args, **kwargs):", "  api.run_script(*args, stdout=_stdout, **kwargs)", ""])
                # the command runs the script on a thread of its own, which outlives the command.
                console_widget.insert_lines([f"import threading; threading.Thread(target=run_script, kwargs={{'file_path': {str(script_path)!r}}}, daemon=True).start()"])
                continue_path.touch()
                start_time = time.time()
                while not written_path.exists() and time.time() - start_time < 10.0:
                    time.sleep(0.01)
                self.assertIn("written after the command returned", sys.stdout.getvalue())
            finally:
                # release the thread in any case, so that it finishes with the test.
                continue_path.touch()
                sys.stdout = stdout
                console_widget.close()


if __name__ == '__main__':
    unittest.main()
