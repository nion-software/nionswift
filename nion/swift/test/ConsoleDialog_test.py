# standard libraries
import io
import sys
import threading
import unittest

# local libraries
from nion.swift import ConsoleDialog


class TestConsoleDialogClass(unittest.TestCase):

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


if __name__ == '__main__':
    unittest.main()
