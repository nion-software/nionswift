# standard libraries
import typing

# third party libraries
# None

# local libraries
import uuid

from nion.swift.model import Persistence


class WorkspaceLayout(Persistence.PersistentObject):
    """
        Represents a specific layout available in the workspace.

        A layout consists of a set of panels within other canvas items and includes
        content of each of those panels.
    """
    def __init__(self) -> None:
        super().__init__()
        self.define_type("workspace")
        self.define_property("name", str(), hidden=True)
        self.define_property("layout", dict(), hidden=True)
        self.define_property("workspace_id", str(uuid.uuid4()), hidden=True)

    @property
    def name(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("name"))

    @name.setter
    def name(self, value: str) -> None:
        self._set_persistent_property_value("name", value)

    @property
    def layout(self) -> Persistence.PersistentDictType:
        return typing.cast(Persistence.PersistentDictType, self._get_persistent_property_value("layout"))

    @layout.setter
    def layout(self, value: Persistence.PersistentDictType) -> None:
        self._set_persistent_property_value("layout", value)

    @property
    def workspace_id(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("workspace_id"))

    @workspace_id.setter
    def workspace_id(self, value: str) -> None:
        self._set_persistent_property_value("workspace_id", value)


def factory(lookup_id: typing.Callable[[str], str]) -> WorkspaceLayout:
    return WorkspaceLayout()
