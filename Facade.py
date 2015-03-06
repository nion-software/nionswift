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
from nion.ui import CanvasItem
from nion.ui import Geometry


__all__ = ["load"]


class FacadeCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(FacadeCanvasItem, self).__init__()
        self.on_repaint = None

    def _repaint(self, drawing_context):
        if self.on_repaint:
            self.on_repaint(drawing_context, Geometry.IntSize.make(self.canvas_size))


class FacadeRootCanvasItem(CanvasItem.RootCanvasItem):

    def __init__(self, ui, canvas_item, properties):
        super(FacadeRootCanvasItem, self).__init__(ui, properties)
        self.__canvas_item = canvas_item

    @property
    def _widget(self):
        return self.canvas_widget

    @property
    def on_repaint(self):
        return self.__canvas_item.on_repaint

    @on_repaint.setter
    def on_repaint(self, value):
        self.__canvas_item.on_repaint = value


class FacadeColumnWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__column_widget = self.__ui.create_column_widget()

    @property
    def _widget(self):
        return self.__column_widget

    def add_spacing(self, spacing):
        self.__column_widget.add_spacing(spacing)

    def add_stretch(self):
        self.__column_widget.add_stretch()

    def add(self, widget):
        self.__column_widget.add(widget._widget)


class FacadeRowWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__row_widget = self.__ui.create_row_widget()

    @property
    def _widget(self):
        return self.__row_widget

    def add_spacing(self, spacing):
        self.__row_widget.add_spacing(spacing)

    def add_stretch(self):
        self.__row_widget.add_stretch()

    def add(self, widget):
        self.__row_widget.add(widget._widget)


class FacadeLabelWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__label_widget = self.__ui.create_label_widget()

    @property
    def _widget(self):
        return self.__label_widget

    @property
    def text(self):
        return self.__label_widget.text

    @text.setter
    def text(self, value):
        self.__label_widget.text = value


class FacadeLineEditWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__line_edit_widget = self.__ui.create_line_edit_widget()

    @property
    def _widget(self):
        return self.__line_edit_widget

    @property
    def text(self):
        return self.__line_edit_widget.text

    @text.setter
    def text(self, value):
        self.__line_edit_widget.text = value

    @property
    def on_editing_finished(self):
        return self.__line_edit_widget.on_editing_finished

    @on_editing_finished.setter
    def on_editing_finished(self, value):
        self.__line_edit_widget.on_editing_finished = value

    def select_all(self):
        self.__line_edit_widget.select_all()


class FacadePushButtonWidget(object):

    def __init__(self, ui):
        self.__ui = ui
        self.__push_button_widget = self.__ui.create_push_button_widget()

    @property
    def _widget(self):
        return self.__push_button_widget

    @property
    def text(self):
        return self.__push_button_widget.text

    @text.setter
    def text(self, value):
        self.__push_button_widget.text = value

    @property
    def on_clicked(self):
        return self.__push_button_widget.on_clicked

    @on_clicked.setter
    def on_clicked(self, value):
        self.__push_button_widget.on_clicked = value


class FacadeUserInterface(object):

    def __init__(self, manifest, ui):
        version = manifest.get("ui", "0")
        version_components = version.split(".")
        if int(version_components[0]) != 1 or len(version_components) > 1:
            raise NotImplementedError("Facade version %s is not available." % version)

        self.__manifest = manifest
        self.__ui = ui

    def create_canvas_widget(self, height=None):
        properties = dict()
        if height is not None:
            properties["min-height"] = height
            properties["max-height"] = height
        canvas_item = FacadeCanvasItem()
        root_canvas_item = FacadeRootCanvasItem(self.__ui, canvas_item, properties=properties)
        root_canvas_item.add_canvas_item(canvas_item)
        return root_canvas_item

    def create_column_widget(self):
        return FacadeColumnWidget(self.__ui)

    def create_row_widget(self):
        return FacadeRowWidget(self.__ui)

    def create_label_widget(self, text=None):
        label_widget = FacadeLabelWidget(self.__ui)
        label_widget.text = text
        return label_widget

    def create_line_edit_widget(self, text=None):
        line_edit_widget = FacadeLineEditWidget(self.__ui)
        line_edit_widget.text = text
        return line_edit_widget

    def create_push_button_widget(self, text=None):
        push_button_widget = FacadePushButtonWidget(self.__ui)
        push_button_widget.text = text
        return push_button_widget


class FacadePanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(FacadePanel, self).__init__(document_controller, panel_id, panel_id)
        self.on_close = None

    def close(self):
        if self.on_close:
            self.on_close()


class FacadeDocumentController(object):

    def __init__(self, manifest, ui):
        self.__manifest = manifest
        self.__ui = ui


class Facade(object):

    def __init__(self, manifest):
        super(Facade, self).__init__()
        self.__manifest = manifest

    def create_panel(self, panel_delegate):
        """Create a utility panel that can be attached to a window.

         The panel_delegate should respond to the following:
            (property, read-only) panel_id
            (property, read-only) panel_name
            (property, read-only) panel_positions (a list from "top", "bottom", "left", "right", "all")
            (property, read-only) panel_position (from "top", "bottom", "left", "right", "none")
            (method, required) create_panel_widget(ui), returns a widget
            (method, optional) close()
        """

        panel_id = panel_delegate.panel_id
        panel_name = panel_delegate.panel_name
        panel_positions = getattr(panel_delegate, "panel_positions", ["left", "right"])
        panel_position = getattr(panel_delegate, "panel_position", "none")
        properties = getattr(panel_delegate, "panel_properties", None)

        def create_facade_panel(document_controller, panel_id, properties):
            panel = FacadePanel(document_controller, panel_id, properties)
            ui = FacadeUserInterface(self.__manifest, document_controller.ui)
            document_controller = FacadeDocumentController(self.__manifest, document_controller.ui)
            panel.widget = panel_delegate.create_panel_widget(ui, document_controller)._widget
            return panel

        workspace_manager = Workspace.WorkspaceManager()
        workspace_manager.register_panel(create_facade_panel, panel_id, panel_name, panel_positions, panel_position, properties)


def load(manifest):
    """Load a facade interface matching the given version.

    version is a string and the only supported version is "1".
    """
    version = manifest.get("main", "0")
    version_components = version.split(".")
    if int(version_components[0]) != 1 or len(version_components) > 1:
        raise NotImplementedError("Facade version %s is not available." % version)
    return Facade(manifest)


# TODO: facade panels never get closed
