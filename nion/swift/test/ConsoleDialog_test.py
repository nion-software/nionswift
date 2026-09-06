# standard libraries
import datetime
import pathlib
import tempfile
import typing
import unittest

# local libraries
from nion.swift import ConsoleDialog
from nion.swift.model import ApplicationData
from nion.utils import DateTime


class MemoryApplicationData:
    """An application data storage for testing."""

    def __init__(self) -> None:
        self.data_dict: typing.Dict[str, typing.Any] = dict()

    def get_data_dict(self) -> typing.Dict[str, typing.Any]:
        return dict(self.data_dict)

    def set_data_dict(self, d: typing.Mapping[str, typing.Any]) -> None:
        self.data_dict = dict(d)


class TestConsoleHistoryStoreClass(unittest.TestCase):

    def test_commands_are_persisted_and_reloaded(self) -> None:
        application_data = MemoryApplicationData()
        store = ConsoleDialog.ConsoleHistoryStore(application_data)
        store.append_command("a = 1")
        store.append_command("b = 2")
        # a new store, simulating a restart, sees the same commands.
        self.assertEqual(["a = 1", "b = 2"], ConsoleDialog.ConsoleHistoryStore(application_data).get_commands())

    def test_commands_are_persisted_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            file_path = pathlib.Path(d) / "data.json"
            store = ConsoleDialog.ConsoleHistoryStore(ApplicationData.ApplicationData(file_path))
            store.append_command("a = 1")
            self.assertTrue(file_path.exists())
            # a new application data object, simulating a restart, reads the persisted commands.
            self.assertEqual(["a = 1"], ConsoleDialog.ConsoleHistoryStore(ApplicationData.ApplicationData(file_path)).get_commands())

    def test_blank_commands_are_not_persisted(self) -> None:
        application_data = MemoryApplicationData()
        store = ConsoleDialog.ConsoleHistoryStore(application_data)
        store.append_command(str())
        store.append_command("   \t ")
        store.append_command("a = 1")
        self.assertEqual(["a = 1"], store.get_commands())

    def test_old_commands_are_pruned(self) -> None:
        application_data = MemoryApplicationData()
        old_timestamp = (DateTime.utcnow() - ConsoleDialog.ConsoleHistoryStore.retention - datetime.timedelta(minutes=1)).isoformat()
        application_data.set_data_dict({"console_history": {"entries": [{"text": "old", "timestamp": old_timestamp}]}})
        store = ConsoleDialog.ConsoleHistoryStore(application_data)
        store.append_command("new")
        self.assertEqual(["new"], store.get_commands())

    def test_commands_are_capped(self) -> None:
        application_data = MemoryApplicationData()
        store = ConsoleDialog.ConsoleHistoryStore(application_data)
        count = ConsoleDialog.ConsoleHistoryStore.max_entries + 10
        for i in range(count):
            store.append_command(f"a = {i}")
        commands = store.get_commands()
        self.assertEqual(ConsoleDialog.ConsoleHistoryStore.max_entries, len(commands))
        self.assertEqual(f"a = {count - 1}", commands[-1])
        self.assertEqual(f"a = {count - ConsoleDialog.ConsoleHistoryStore.max_entries}", commands[0])

    def test_invalid_entries_are_ignored(self) -> None:
        application_data = MemoryApplicationData()
        entries = [{"text": "no timestamp"}, {"timestamp": "not-a-date", "text": "bad timestamp"}, "not a dict"]
        application_data.set_data_dict({"console_history": {"entries": entries}})
        self.assertEqual([], ConsoleDialog.ConsoleHistoryStore(application_data).get_commands())


class TestConsoleWidgetStateControllerClass(unittest.TestCase):

    def test_new_console_loads_persisted_history(self) -> None:
        application_data = MemoryApplicationData()
        history_store = ConsoleDialog.ConsoleHistoryStore(application_data)
        state_controller = ConsoleDialog.ConsoleWidgetStateController(dict(), history_store=history_store)
        state_controller.interpret_command("a = 1")
        state_controller.close()
        # a new console loads the persisted history.
        state_controller = ConsoleDialog.ConsoleWidgetStateController(dict(), history_store=history_store)
        self.assertEqual("a = 1", state_controller.move_back_in_history(str()))
        state_controller.close()

    def test_blank_command_is_not_persisted_by_console(self) -> None:
        application_data = MemoryApplicationData()
        history_store = ConsoleDialog.ConsoleHistoryStore(application_data)
        state_controller = ConsoleDialog.ConsoleWidgetStateController(dict(), history_store=history_store)
        state_controller.interpret_command(str())
        state_controller.interpret_command("   ")
        state_controller.close()
        self.assertEqual([], history_store.get_commands())

    def test_open_consoles_append_to_shared_history_but_do_not_refresh(self) -> None:
        application_data = MemoryApplicationData()
        history_store = ConsoleDialog.ConsoleHistoryStore(application_data)
        state_controller1 = ConsoleDialog.ConsoleWidgetStateController(dict(), history_store=history_store)
        state_controller2 = ConsoleDialog.ConsoleWidgetStateController(dict(), history_store=history_store)
        state_controller1.interpret_command("a = 1")
        state_controller2.interpret_command("b = 2")
        # the already open console does not see the command from the other console.
        self.assertEqual("b = 2", state_controller2.move_back_in_history(str()))
        self.assertEqual("b = 2", state_controller2.move_back_in_history("b = 2"))
        # but both commands are in the shared history.
        self.assertEqual(["a = 1", "b = 2"], history_store.get_commands())
        state_controller1.close()
        state_controller2.close()

    def test_history_navigation_is_unchanged(self) -> None:
        state_controller = ConsoleDialog.ConsoleWidgetStateController(dict(), history_store=ConsoleDialog.ConsoleHistoryStore(MemoryApplicationData()))
        state_controller.interpret_command("a = 1")
        state_controller.interpret_command("b = 2")
        self.assertEqual("b = 2", state_controller.move_back_in_history(str()))
        self.assertEqual("a = 1", state_controller.move_back_in_history("b = 2"))
        self.assertEqual("b = 2", state_controller.move_forward_in_history("a = 1"))
        self.assertEqual(str(), state_controller.move_forward_in_history("b = 2"))
        state_controller.close()


if __name__ == '__main__':
    unittest.main()
