# standard libraries
import unittest

# local libraries
from nion.swift.model.computation_api import v1 as computation_api
from nion.swift.model.computation_api.v1 import protocols as computation_api_v1_protocols


class _TestExecutor(computation_api_v1_protocols.Executor):
    def execute(self, parameters: computation_api_v1_protocols.Parameters) -> computation_api_v1_protocols.Outputs:
        return {"result": 1}


class TestComputationAPIClass(unittest.TestCase):

    def setUp(self) -> None:
        computation_api.clear_configuration()

    def tearDown(self) -> None:
        computation_api.clear_configuration()

    def test_register_executor_raises_if_not_configured(self) -> None:
        with self.assertRaises(RuntimeError) as cm:
            computation_api.get_api().register_executor("test.operation", _TestExecutor())
        self.assertEqual("computation_api.v1 is not configured by host", str(cm.exception))

    def test_register_executor_calls_configured_callback(self) -> None:
        registered_operation_ids = list[str]()

        def register_callback(operation_id: str, executor: computation_api.Executor) -> None:
            registered_operation_ids.append(operation_id)

        computation_api.configure(register_callback)
        computation_api.get_api().register_executor("test.operation", _TestExecutor())

        self.assertEqual(["test.operation"], registered_operation_ids)

    def test_clear_configuration_requires_reconfigure(self) -> None:
        first_registered_operation_ids = list[str]()
        second_registered_operation_ids = list[str]()

        def first_register_callback(operation_id: str, executor: computation_api.Executor) -> None:
            first_registered_operation_ids.append(operation_id)

        def second_register_callback(operation_id: str, executor: computation_api.Executor) -> None:
            second_registered_operation_ids.append(operation_id)

        computation_api.configure(first_register_callback)
        computation_api.get_api().register_executor("test.operation", _TestExecutor())

        computation_api.clear_configuration()

        with self.assertRaises(RuntimeError):
            computation_api.get_api().register_executor("test.operation", _TestExecutor())

        computation_api.configure(second_register_callback)
        computation_api.get_api().register_executor("test.operation", _TestExecutor())

        self.assertEqual(["test.operation"], first_registered_operation_ids)
        self.assertEqual(["test.operation"], second_registered_operation_ids)


    def test_register_executor_rejects_empty_operation_id(self) -> None:
        computation_api.configure(lambda operation_id, executor: None)
        with self.assertRaises(ValueError):
            computation_api.get_api().register_executor("", _TestExecutor())

