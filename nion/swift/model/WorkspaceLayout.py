# standard libraries
# None

# third party libraries
# None

# local libraries
from nion.utils import Persistence


class WorkspaceLayout(Persistence.PersistentObject):
    """
        Represents a specific layout available in the workspace.

        A layout consists of a set of panels within other canvas items and includes
        content of each of those panels.
    """
    def __init__(self):
        super(WorkspaceLayout, self).__init__()
        self.define_type("workspace")
        self.define_property("name")
        self.define_property("layout")
        self.define_property("workspace_id")


def factory(lookup_id):
    return WorkspaceLayout()
