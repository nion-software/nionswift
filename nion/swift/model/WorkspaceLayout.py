# standard libraries
import datetime
import typing

# third party libraries
# None

# local libraries
import uuid

from nion.swift.model import Persistence
from nion.swift.model.Persistence import PersistentDictType
from nion.utils import Converter
from nion.utils import DateTime


class WorkspaceLayout(Persistence.PersistentObject):
    """
        Represents a specific layout available in the workspace.

        A layout consists of a set of panels within other canvas items and includes
        content of each of those panels.
    """
    def __init__(self) -> None:
        super().__init__()
        self.define_type("workspace")
        self.define_property("created", DateTime.utcnow(), hidden=True, converter=Converter.DatetimeToStringConverter())
        self.define_property("name", str(), hidden=True)
        self.define_property("layout", dict(), hidden=True)
        self.define_property("workspace_id", str(uuid.uuid4()), hidden=True)
        # created was not originally available, so now we always set created when creating a new object.
        # however, there is special logic so that if we load an old object without created, we set it
        # when the object context is set. this variable is used to facilitate that. this scheme avoids
        # writing the file until there is another reason to write the file.
        self.__needs_created_update = False

    def read_from_dict(self, properties: PersistentDictType) -> None:
        super().read_from_dict(properties)
        # we're reading an old object, so check if it contained 'created'. if not, we will set it
        # when the object context is set.
        self.__needs_created_update = properties.get("created") is None

    def persistent_object_context_changed(self) -> None:
        super().persistent_object_context_changed()
        if self.__needs_created_update:
            # update 'created' in a way so that if the project properties get written out due to
            # other changes, the 'created' property gets written out too. do this by marking it as
            # a ghost property while setting it.
            self.ghost_properties.update(["created"])
            try:
                # update like this to avoid updating modified time on parent objects.
                self._get_persistent_property("created").value = self.modified
                self._update_persistent_object_context_property("created")
            finally:
                self.ghost_properties.subtract("created")
            self.__needs_created_update = False

    @property
    def created(self) -> datetime.datetime:
        return typing.cast(datetime.datetime, self._get_persistent_property_value("created"))

    def _set_created(self, value: datetime.datetime) -> None:
        self._set_persistent_property_value("created", value)

    @property
    def timestamp_for_sorting(self) -> datetime.datetime:
        created = self.created
        return created if created else self.modified

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
