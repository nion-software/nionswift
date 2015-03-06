"""
    A versioned interface to Swift.

    on_xyz methods are used when a callback needs a return value and has only a single listener.

    events are used when a callback is optional and may have multiple listeners.

    Versions numbering follows semantic versioning: http://semver.org/
"""

# standard libraries
# None

# third party libraries
# None

# local libraries
from nion.swift.model import Utility
from nion.swift import Panel
from nion.swift import Workspace


__all__ = ["load"]


class FacadePanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(FacadePanel, self).__init__(document_controller, panel_id, panel_id)
        self.on_close = None

    def close(self):
        if self.on_close:
            self.on_close()


class UserInterfaceFactory(object):

    def __init__(self, ui):
        self.__ui = ui

    def make(self, version):
        if version == "1":
            return self.__ui
        raise NotImplementedError("Version not specified for UserInterface object.")


class Facade(object):
    __metaclass__ = Utility.Singleton

    def __init__(self):
        super(Facade, self).__init__()

    def create_panel(self, panel_delegate):
        """Create a utility panel that can be attached to a window.

         The panel_delegate should respond to the following:
            (read-only property) panel_id
            (read-only property) panel_name
            (read-only property) panel_positions (a list from "top", "bottom", "left", "right", "all")
            (read-only property) panel_position (from "top", "bottom", "left", "right", "none")
            (method) create_panel_widget(ui), returns a widget
            (method) close()
        """

        panel_id = panel_delegate.panel_id
        panel_name = panel_delegate.panel_name
        panel_positions = getattr(panel_delegate, "panel_positions", ["left", "right"])
        panel_position = getattr(panel_delegate, "panel_position", "none")
        properties = getattr(panel_delegate, "panel_properties", None)

        def create_facade_panel(document_controller, panel_id, properties):
            panel = FacadePanel(document_controller, panel_id, properties)
            panel.widget = panel_delegate.create_panel_widget(UserInterfaceFactory(document_controller.ui))
            return panel

        workspace_manager = Workspace.WorkspaceManager()
        workspace_manager.register_panel(create_facade_panel, panel_id, panel_name, panel_positions, panel_position, properties)


def load(version):
    """Load a facade interface matching the given version.

    version is a string and the only supported version is "1".
    """
    version_components = version.split(".")
    if int(version_components[0]) != 1 or len(version_components) > 1:
        raise NotImplementedError("Facade version %s is not available." % version)
    return Facade()


# TODO: facade panels never get closed
