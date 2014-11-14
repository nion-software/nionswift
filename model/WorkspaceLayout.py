# standard libraries
# None

# third party libraries
# None

# local libraries
from nion.ui import Observable


class Workspace(Observable.ManagedObject):
    """
        Represents a specific layout available in the workspace.

        A layout consists of a set of panels within other canvas items and includes
        content of each of those panels.
    """
    def __init__(self):
        super(Workspace, self).__init__()
        self.define_type("workspace")
        self.define_property("name")
        self.define_property("layout")


def factory(lookup_id):
    return Workspace()
