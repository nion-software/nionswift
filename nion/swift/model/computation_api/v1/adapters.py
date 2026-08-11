"""Adapters for computation API v1."""

import dataclasses
import typing

import nion.swift.model.computation_api.v1.protocols as computation_protocols

_RegisterExecutorCallable = typing.Callable[[str, computation_protocols.Executor], None]
_register_executor: _RegisterExecutorCallable | None = None


@dataclasses.dataclass(frozen=True)
class RegistrationAPI:
	"""Registration adapter exposed to computation plugins."""

	def register_executor(self, operation_id: str, executor: computation_protocols.Executor) -> None:
		if _register_executor is None:
			raise RuntimeError("computation_api.v1 is not configured by host")
		if not operation_id:
			raise ValueError("operation_id must not be empty")
		register_executor = _register_executor
		register_executor(operation_id, executor)


_registration_api = RegistrationAPI()


def configure(register_executor: _RegisterExecutorCallable) -> None:
	"""Configure host callbacks for registration.

	This function is intended for host use before loading plugins.
	"""
	global _register_executor
	_register_executor = register_executor


def clear_configuration() -> None:
	"""Clear host callback configuration.

	This function is useful for tests and plugin reload flows.
	"""
	global _register_executor
	_register_executor = None


def get_api() -> RegistrationAPI:
	return _registration_api


__all__ = ["RegistrationAPI", "clear_configuration", "configure", "get_api"]

