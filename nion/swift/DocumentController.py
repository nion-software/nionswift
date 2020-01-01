# standard libraries
import collections
import copy
import datetime
import functools
import gettext
import itertools
import logging
import math
import operator
import os.path
import pathlib
import pkgutil
import sys
import threading
import time
import traceback
import typing
import uuid
import weakref

from nion.data import DataAndMetadata
from nion.swift import ComputationPanel
from nion.swift import ConsoleDialog
from nion.swift import DisplayEditorPanel
from nion.swift import DisplayPanel
from nion.swift import ExportDialog
from nion.swift import FilterPanel
from nion.swift import MimeTypes
from nion.swift import RecorderPanel
from nion.swift import ScriptsDialog
from nion.swift import Task
from nion.swift import Undo
from nion.swift import Workspace
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import ImportExportManager
from nion.swift.model import Processing
from nion.swift.model import Profile
from nion.swift.model import Project
from nion.swift.model import Symbolic
from nion.ui import CanvasItem
from nion.ui import Dialog
from nion.ui import PreferencesDialog
from nion.ui import Window
from nion.ui import UserInterface
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Registry
from nion.utils import Selection

_ = gettext.gettext


class DocumentController(Window.Window):
    """Manage a document window."""

    def __init__(self, ui, document_model, workspace_id=None, app=None):
        super().__init__(ui, app)

        self.__undo_stack = Undo.UndoStack()

        if not app:
            self.event_loop.has_no_pulse = True

        self.__closed = False  # debugging

        self.uuid = uuid.uuid4()

        self.task_created_event = Event.Event()
        self.cursor_changed_event = Event.Event()
        self.did_close_event = Event.Event()
        self.create_new_document_controller_event = Event.Event()
        self.tool_mode_changed_event = Event.Event()

        self.__dialogs = list()

        self.__last_activity = None

        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model = document_model
        self.document_model.add_ref()
        self.title = _("Nion Swift")
        self.__workspace_controller = None
        self.replaced_display_panel_content = None  # used to facilitate display panel functionality to exchange displays
        self.__weak_selected_display_panel = None
        self.__tool_mode = "pointer"
        self.__weak_periodic_listeners = []
        self.__weak_periodic_listeners_mutex = threading.RLock()

        self.selection = Selection.IndexedSelection()

        # the user has two ways of filtering data items: first by selecting a data group (or none) in the data panel,
        # and next by applying a custom filter to the items from the items resulting in the first selection.
        # data items model tracks the main list of items selected in the data panel.
        # filtered display items model tracks the filtered items from those in data items model.
        self.__display_items_model = ListModel.FilteredListModel(container=self.document_model, items_key="display_items")
        self.__display_items_model.filter_id = None  # extra tracking field
        self.__filtered_display_items_model = ListModel.FilteredListModel(items_key="display_items", container=self.__display_items_model)
        self.__last_display_filter = ListModel.Filter(True)
        self.filter_changed_event = Event.Event()
        self.active_projects_changed_event = Event.Event()

        self.__update_display_items_model(self.__display_items_model, None, None)

        def call_soon(fn):
            self.queue_task(fn)
            return True

        self.__call_soon_event_listener = self.document_model.call_soon_event.listen(call_soon)

        self.filter_controller = FilterPanel.FilterController(self)

        self.focused_display_item_changed_event = Event.Event()
        self.__focused_display_item = None
        self.notify_focused_display_changed(None)

        self.__consoles = list()

        self._create_menus()
        if workspace_id:  # used only when testing reference counting
            self.__workspace_controller = Workspace.Workspace(self, workspace_id)
            self.__workspace_controller.restore(self.document_model.workspace_uuid)

    def close(self):
        """Close the document controller.

        This method must be called to shut down the document controller. There are several
        paths by which it can be called, though.

           * User quits application via menu item. The menu item will call back to Application.exit which will close each
             document controller by calling this method.
           * User quits application using dock menu item. The Qt application will call aboutToClose in the document windows
           * User closes document window via menu item.
           * User closes document window via close box.

        The main concept of closing is that it is always triggered by the document window closing. This can be initiated
        from within Python by calling request_close on the document window. When the window closes, either by explicit request
        or by the user clicking a close box, it will invoke the about_to_close method on the document window. At this point,
        the window would still be open, so the about_to_close message can be used to tell the document controller to save anything
        it needs to save and prepare for closing.
        """
        assert self.__closed == False
        self.__closed = True
        self.finish_periodic()  # required to finish periodic operations during tests
        # dialogs
        for weak_dialog in self.__dialogs:
            dialog = weak_dialog()
            if dialog:
                try:
                    dialog.request_close()
                except Exception as e:
                    pass
        # menus
        self._file_menu = None
        self._edit_menu = None
        self._processing_menu = None
        self._view_menu = None
        self._window_menu = None
        self._help_menu = None
        self._processing_arithmetic_menu = None
        self._processing_reduce_menu = None
        self._processing_transform_menu = None
        self._processing_filter_menu = None
        self._processing_fourier_menu = None
        self._processing_graphics_menu = None
        self._processing_sequence_menu = None
        self._processing_redimension_menu = None
        self._display_type_menu = None

        if self.__workspace_controller:
            self.__workspace_controller.close()
            self.__workspace_controller = None
        self.__call_soon_event_listener.close()
        self.__call_soon_event_listener = None
        self.__filtered_display_items_model.close()
        self.__filtered_display_items_model = None
        self.filter_controller.close()
        self.filter_controller = None
        self.__display_items_model.close()
        self.__display_items_model = None
        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model.remove_ref()
        self.document_model = None
        self.did_close_event.fire(self)
        self.did_close_event = None
        super().close()

    def _register_ui_activity(self):
        self.__last_activity = time.time()

    def about_to_show(self):
        geometry, state = self.workspace_controller.restore_geometry_state()
        self.restore(geometry, state)

    def about_to_close(self, geometry, state):
        if self.workspace_controller:
            self.workspace_controller.save_geometry_state(geometry, state)
        super().about_to_close(geometry, state)

    def register_console(self, console):
        self.__consoles.append(console)

    def unregister_console(self, console):
        self.__consoles.remove(console)

    def _create_menus(self):
        # don't use default implementation

        self._file_menu = self.add_menu(_("File"))

        self._edit_menu = self.add_menu(_("Edit"))

        self._processing_menu = self.add_menu(_("Processing"))

        self._view_menu = self.add_menu(_("View"))

        self._window_menu = self.add_menu(_("Window"))

        self._help_menu = self.add_menu(_("Help"))

        self._new_window_action = self._file_menu.add_menu_item(_("New Window"), functools.partial(self.new_window_with_data_item, "library"), key_sequence="new")
        self._close_action = self._file_menu.add_menu_item(_("Close Window"), self.request_close, key_sequence="close")
        self._file_menu.add_separator()
        self._new_library_action = self._file_menu.add_menu_item(_("New Project..."), self.__handle_new_project)
        self._add_project_action = self._file_menu.add_menu_item(_("Open Project..."), self.__handle_open_project)
        self._migrate_project_action = self._file_menu.add_menu_item(_("Upgrade Project"), self.__handle_upgrade_project)
        self._remove_project_action = self._file_menu.add_menu_item(_("Remove Project"), self.__handle_remove_project)
        self._file_menu.add_separator()
        self._remove_project_action = self._file_menu.add_menu_item(_("Set Work Project"), self.__set_work_project)
        self._file_menu.add_separator()
        self._import_folder_action = self._file_menu.add_menu_item(_("Import Folder..."), self.__import_folder)
        self._import_action = self._file_menu.add_menu_item(_("Import Data..."), self.import_file)
        def export_files():
            selected_display_items = self.selected_display_items
            if len(selected_display_items) > 1:
                self.export_files(selected_display_items)
            elif len(selected_display_items) == 1:
                self.export_file(selected_display_items[0])
            elif self.selected_display_item:
                self.export_file(self.selected_display_item)
        self._export_action = self._file_menu.add_menu_item(_("Export..."), export_files)
        def export_svg():
            selected_display_item = self.selected_display_item
            if selected_display_item:
                self.export_svg(selected_display_item)
        self._export_svg_action = self._file_menu.add_menu_item(_("Export SVG..."), export_svg)
        #self._file_menu.add_separator()
        #self._save_action = self._file_menu.add_menu_item(_("Save"), self.no_operation, key_sequence="save")
        #self._save_as_action = self._file_menu.add_menu_item(_("Save As..."), self.no_operation, key_sequence="save-as")
        self._file_menu.add_separator()
        self._file_menu.add_menu_item(_("Scripts..."), self.new_interactive_script_dialog, key_sequence="Ctrl+R")
        self._file_menu.add_menu_item(_("Python Console..."), self.new_console_dialog, key_sequence="Ctrl+K")
        self._file_menu.add_separator()
        self._add_group_action = self._file_menu.add_menu_item(_("Add Group"), self.add_group)
        self._file_menu.add_separator()
        self._page_setup_action = self._file_menu.add_menu_item(_("Page Setup"), self._page_setup)
        self._print_action = self._file_menu.add_menu_item(_("Print"), self._print, key_sequence="Ctrl+P")
        self._file_menu.add_separator()
        self._quit_action = self._file_menu.add_menu_item(_("Exit"), lambda: self.app.exit(), key_sequence="quit", role="quit")

        self._undo_action = self._edit_menu.add_menu_item(_("Undo"), self._undo, key_sequence="undo")
        self._redo_action = self._edit_menu.add_menu_item(_("Redo"), self._redo, key_sequence="redo")
        self._edit_menu.add_separator()
        self._cut_action = self._edit_menu.add_menu_item(_("Cut"), self._cut, key_sequence="cut")
        self._copy_action = self._edit_menu.add_menu_item(_("Copy"), self._copy, key_sequence="copy")
        # self._deep_copy_action = self._edit_menu.add_menu_item(_("Deep Copy"), self.__deep_copy, key_sequence="Ctrl+Shift+C")
        self._paste_action = self._edit_menu.add_menu_item(_("Paste"), self._paste, key_sequence="paste")
        self._delete_action = self._edit_menu.add_menu_item(_("Delete"), self._delete, key_sequence="delete")
        self._select_all_action = self._edit_menu.add_menu_item(_("Select All"), self._select_all, key_sequence="select-all")
        self._edit_menu.add_separator()
        self._script_action = self._edit_menu.add_menu_item(_("Assign Variable Reference"), self.prepare_data_item_script, key_sequence="Ctrl+Shift+K")
        self._copy_uuid_action = self._edit_menu.add_menu_item(_("Copy Item UUID"), self.copy_uuid, key_sequence="Ctrl+Shift+U")
        self._empty_data_item_action = self._edit_menu.add_menu_item(_("Create New Data Item"), self.create_empty_data_item)
        self._edit_menu.add_separator()
        self.properties_action = self._edit_menu.add_menu_item(_("Preferences..."), self.open_preferences, role="preferences")

        # these are temporary menu items, so don't need to assign them to variables, for now
        self._processing_graphics_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Graphics"), self._processing_graphics_menu)
        self._processing_menu.add_separator()

        self._processing_graphics_menu.add_menu_item(_("Add Line Graphic"), self.add_line_graphic)
        self._processing_graphics_menu.add_menu_item(_("Add Ellipse Graphic"), self.add_ellipse_graphic)
        self._processing_graphics_menu.add_menu_item(_("Add Rectangle Graphic"), self.add_rectangle_graphic)
        self._processing_graphics_menu.add_menu_item(_("Add Point Graphic"), self.add_point_graphic)
        self._processing_graphics_menu.add_menu_item(_("Add Interval Graphic"), self.add_interval_graphic)
        self._processing_graphics_menu.add_menu_item(_("Add Channel Graphic"), self.add_channel_graphic)
        self._processing_graphics_menu.add_separator()
        self._processing_graphics_menu.add_menu_item(_("Add to Mask"), self.add_graphic_mask)
        self._processing_graphics_menu.add_menu_item(_("Remove from Mask"), self.remove_graphic_mask)

        self._processing_menu.add_menu_item(_("Snapshot"), self.processing_snapshot, key_sequence="Ctrl+S")
        self._processing_menu.add_menu_item(_("Duplicate"), self.processing_duplicate, key_sequence="Ctrl+D")
        self._processing_menu.add_separator()

        self._processing_menu.add_menu_item(_("Edit Data Item Scripts"), self.new_edit_computation_dialog, key_sequence="Ctrl+E")
        self._processing_menu.add_menu_item(_("Edit Display Script"), self.new_display_editor_dialog, key_sequence="Ctrl+Shift+D")
        self._processing_menu.add_separator()

        self._processing_transform_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Transform"), self._processing_transform_menu)

        self._processing_transform_menu.add_menu_item(_("Transpose and Flip"), functools.partial(self.__processing_new, self.document_model.get_transpose_flip_new))
        self._processing_transform_menu.add_menu_item(_("Resample"), functools.partial(self.__processing_new, self.document_model.get_resample_new))
        self._processing_transform_menu.add_menu_item(_("Crop"), functools.partial(self.__processing_new, self.document_model.get_crop_new))
        self._processing_transform_menu.add_menu_item(_("Resize"), functools.partial(self.__processing_new, self.document_model.get_resize_new))
        self._processing_transform_menu.add_menu_item(_("Convert to Scalar"), functools.partial(self.__processing_new, self.document_model.get_convert_to_scalar_new))

        self._processing_arithmetic_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Arithmetic"), self._processing_arithmetic_menu)

        self._processing_arithmetic_menu.add_menu_item(_("Add"), functools.partial(self.__processing_new2, self.document_model.get_add_new))
        self._processing_arithmetic_menu.add_menu_item(_("Subtract"), functools.partial(self.__processing_new2, self.document_model.get_subtract_new))
        self._processing_arithmetic_menu.add_menu_item(_("Multiply"), functools.partial(self.__processing_new2, self.document_model.get_multiply_new))
        self._processing_arithmetic_menu.add_menu_item(_("Divide"), functools.partial(self.__processing_new2, self.document_model.get_divide_new))
        self._processing_arithmetic_menu.add_menu_item(_("Negate"), functools.partial(self.__processing_new, self.document_model.get_invert_new))
        self._processing_arithmetic_menu.add_separator()
        self._processing_arithmetic_menu.add_menu_item(_("Masked"), functools.partial(self.__processing_new, self.document_model.get_masked_new))
        self._processing_arithmetic_menu.add_menu_item(_("Mask"), functools.partial(self.__processing_new, self.document_model.get_mask_new))
        self._processing_arithmetic_menu.add_separator()
        self._processing_arithmetic_menu.add_menu_item(_("Subtract Region Average"), functools.partial(self.__processing_new, self.document_model.get_subtract_region_average_new))

        self._processing_reduce_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Reduce"), self._processing_reduce_menu)

        self._processing_reduce_menu.add_menu_item(_("Slice Sum"), functools.partial(self.__processing_new, self.document_model.get_slice_sum_new))
        self._processing_reduce_menu.add_menu_item(_("Pick"), functools.partial(self.__processing_new, self.document_model.get_pick_new))
        self._processing_reduce_menu.add_menu_item(_("Pick Region (Sum)"), functools.partial(self.__processing_new, self.document_model.get_pick_region_new))
        self._processing_reduce_menu.add_menu_item(_("Pick Region (Average)"), functools.partial(self.__processing_new, self.document_model.get_pick_region_average_new))
        self._processing_reduce_menu.add_menu_item(_("Projection (Sum)"), functools.partial(self.__processing_new, self.document_model.get_projection_new))
        self._processing_reduce_menu.add_menu_item(_("Mapped Sum"), functools.partial(self.__processing_new, self.document_model.get_mapped_sum_new))
        self._processing_reduce_menu.add_menu_item(_("Mapped Average"), functools.partial(self.__processing_new, self.document_model.get_mapped_average_new))

        self._processing_fourier_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Fourier"), self._processing_fourier_menu)

        self._processing_fourier_menu.add_menu_item(_("FFT"), functools.partial(self.__processing_new, self.document_model.get_fft_new), key_sequence="Ctrl+F")
        self._processing_fourier_menu.add_menu_item(_("Inverse FFT"), functools.partial(self.__processing_new, self.document_model.get_ifft_new), key_sequence="Ctrl+Shift+F")
        self._processing_fourier_menu.add_menu_item(_("Auto Correlate"), functools.partial(self.__processing_new, self.document_model.get_auto_correlate_new))
        self._processing_fourier_menu.add_menu_item(_("Cross Correlate"), self.processing_cross_correlate_new)
        self._processing_fourier_menu.add_menu_item(_("Fourier Filter"), self.processing_fourier_filter_new)

        processing_components = list()
        for processing_component in typing.cast(typing.Sequence[Processing.ProcessingBase], Registry.get_components_by_type("processing-component")):
            if "windows" in processing_component.sections:
                processing_components.append(processing_component)
        if processing_components:
            self._processing_fourier_menu.add_separator()
            for processing_component in sorted(processing_components, key=operator.attrgetter("title")):
                self._processing_fourier_menu.add_menu_item(processing_component.title, functools.partial(self.processing_new, processing_component.processing_id))

        self._processing_fourier_menu.add_separator()
        self._processing_fourier_menu.add_menu_item(_("Add Spot Filter"), self.add_spot_graphic)
        self._processing_fourier_menu.add_menu_item(_("Add Angle Filter"), self.add_angle_graphic)
        self._processing_fourier_menu.add_menu_item(_("Add Band Pass Filter"), self.add_band_pass_graphic)
        self._processing_fourier_menu.add_menu_item(_("Add Lattice Filter"), self.add_lattice_graphic)

        self._processing_filter_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Filter"), self._processing_filter_menu)

        self._processing_filter_menu.add_menu_item(_("Sobel Filter"), functools.partial(self.__processing_new, self.document_model.get_sobel_new))
        self._processing_filter_menu.add_menu_item(_("Laplace Filter"), functools.partial(self.__processing_new, self.document_model.get_laplace_new))
        self._processing_filter_menu.add_menu_item(_("Gaussian Blur"), functools.partial(self.__processing_new, self.document_model.get_gaussian_blur_new))
        self._processing_filter_menu.add_menu_item(_("Median Filter"), functools.partial(self.__processing_new, self.document_model.get_median_filter_new))
        self._processing_filter_menu.add_menu_item(_("Uniform Filter"), functools.partial(self.__processing_new, self.document_model.get_uniform_filter_new))

        self.__data_menu_actions = list()
        self._processing_redimension_menu = self.create_sub_menu()
        self._processing_redimension_menu.on_about_to_show = self.__adjust_redimension_data_menu
        self._processing_menu.add_sub_menu(_("Redimension Data"), self._processing_redimension_menu)

        self._processing_sequence_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Sequence"), self._processing_sequence_menu)

        self._processing_sequence_menu.add_menu_item(_("Measure Shifts"), functools.partial(self.__processing_new, self.document_model.get_sequence_measure_shifts_new))
        self._processing_sequence_menu.add_menu_item(_("Align"), functools.partial(self.__processing_new, self.document_model.get_sequence_align_new))
        self._processing_sequence_menu.add_menu_item(_("Integrate"), functools.partial(self.__processing_new, self.document_model.get_sequence_integrate_new))
        self._processing_sequence_menu.add_menu_item(_("Trim"), functools.partial(self.__processing_new, self.document_model.get_sequence_trim_new))
        self._processing_sequence_menu.add_menu_item(_("Extract"), functools.partial(self.__processing_new, self.document_model.get_sequence_extract_new))

        self._processing_menu.add_menu_item(_("Line Profile"), functools.partial(self.__processing_new, self.document_model.get_line_profile_new))
        self._processing_menu.add_menu_item(_("Histogram"), functools.partial(self.__processing_new, self.document_model.get_histogram_new))
        self._processing_menu.add_separator()

        self.__dynamic_live_actions = []

        def about_to_show_display_type_menu():
            for dynamic_live_action in self.__dynamic_live_actions:
                self._display_type_menu.remove_action(dynamic_live_action)
            self.__dynamic_live_actions = []

            selected_display_panel = self.selected_display_panel
            if not selected_display_panel:
                return

            self.__dynamic_live_actions.extend(DisplayPanel.DisplayPanelManager().build_menu(self._display_type_menu, self, selected_display_panel))

        self._display_type_menu = self.create_sub_menu()
        self._display_type_menu.on_about_to_show = about_to_show_display_type_menu

        self._view_menu.add_sub_menu(_("Display Panel Type"), self._display_type_menu)
        self._view_menu.add_separator()

        self._view_menu.add_menu_item(_("Display Copy"), self.processing_display_copy)
        self._display_remove_action = self._view_menu.add_menu_item(_("Display Remove"), self.processing_display_remove)
        self._view_menu.add_separator()

        # these are temporary menu items, so don't need to assign them to variables, for now
        def fit_to_view():
            if self.selected_display_panel is not None:
                self.selected_display_panel.perform_action("set_fit_mode")

        self._fit_view_action = self._view_menu.add_menu_item(_("Fit to View"), fit_to_view, key_sequence="0")

        def fill_view():
            if self.selected_display_panel is not None:
                self.selected_display_panel.perform_action("set_fill_mode")

        self._fill_view_action = self._view_menu.add_menu_item(_("Fill View"), fill_view, key_sequence="Shift+0")

        def one_to_one_view():
            if self.selected_display_panel is not None:
                self.selected_display_panel.perform_action("set_one_to_one_mode")

        def two_to_one_view():
            if self.selected_display_panel is not None:
                self.selected_display_panel.perform_action("set_two_to_one_mode")

        self._one_to_one_view_action = self._view_menu.add_menu_item(_("1:1 View"), one_to_one_view, key_sequence="1")
        self._two_to_one_view_action = self._view_menu.add_menu_item(_("2:1 View"), two_to_one_view, key_sequence="2")
        self._view_menu.add_separator()
        self._toggle_filter_action = self._view_menu.add_menu_item(_("Filter"), self.toggle_filter, key_sequence="Ctrl+\\")
        self._view_menu.add_separator()
        self._view_menu.add_menu_item(_("Previous Workspace"), self.__change_to_previous_workspace, key_sequence="Ctrl+[")
        self._view_menu.add_menu_item(_("Next Workspace"), self.__change_to_next_workspace, key_sequence="Ctrl+]")
        self._view_menu.add_separator()
        self._view_menu.add_menu_item(_("New Workspace"), self.__create_workspace, key_sequence="Ctrl+Alt+L")
        self._view_menu.add_menu_item(_("Rename Workspace"), self.__rename_workspace)
        self._view_menu.add_menu_item(_("Remove Workspace"), self.__remove_workspace)
        self._view_menu.add_menu_item(_("Clone Workspace"), self.__clone_workspace)
        self._view_menu.add_separator()
        self._view_menu.add_menu_item(_("Data Item Recorder..."), self.new_recorder_dialog, key_sequence="Ctrl+Shift+R")
        self._view_menu.add_separator()

        self.__dynamic_view_actions = []

        def adjust_view_menu():
            for dynamic_view_action in self.__dynamic_view_actions:
                self._view_menu.remove_action(dynamic_view_action)
            self.__dynamic_view_actions = []
            for workspace in self.document_model.workspaces:
                def switch_to_workspace(workspace):
                    self.workspace_controller.change_workspace(workspace)
                action = self._view_menu.add_menu_item(workspace.name, functools.partial(switch_to_workspace, workspace))
                action.checked = self.document_model.workspace_uuid == workspace.uuid
                self.__dynamic_view_actions.append(action)
            selected_display_panel = self.selected_display_panel
            data_item = selected_display_panel.data_item if selected_display_panel else None
            display_items = self.document_model.get_display_items_for_data_item(data_item) if data_item else list()
            self._display_remove_action.enabled = len(display_items) > 1

        self._view_menu.on_about_to_show = adjust_view_menu

        #self.help_action = self._help_menu.add_menu_item(_("Help"), self.no_operation, key_sequence="help")
        self._about_action = self._help_menu.add_menu_item(_("About"), self.show_about_box, role="about")

        self._minimize_action = self._window_menu.add_menu_item(_("Minimize"), self._minimize)
        self._zoom_action = self._window_menu.add_menu_item(_("Zoom"), self._zoom)
        self._bring_to_front_action = self._window_menu.add_menu_item(_("Bring to Front"), self._bring_to_front)
        self._window_menu.add_separator()

        self.__dynamic_window_actions = []

        def adjust_window_menu():
            for dynamic_window_action in self.__dynamic_window_actions:
                self._window_menu.remove_action(dynamic_window_action)
            self.__dynamic_window_actions = []
            toggle_actions = [dock_widget.toggle_action for dock_widget in self.workspace_controller.dock_widgets]
            for toggle_action in sorted(toggle_actions, key=operator.attrgetter("title")):
                self._window_menu.add_action(toggle_action)
                self.__dynamic_window_actions.append(toggle_action)
            self._window_menu_about_to_show()

        self._window_menu.on_about_to_show = adjust_window_menu
        self._file_menu.on_about_to_show = self._file_menu_about_to_show

        def adjust_edit_menu():
            # self._deep_copy_action.apply_state(self._get_focus_widget_menu_item_state("deep_copy"))
            self._edit_menu_about_to_show()

        self._edit_menu.on_about_to_show = adjust_edit_menu

    def get_menu(self, menu_id):
        assert menu_id.endswith("_menu")
        return getattr(self, menu_id, None)

    def get_or_create_menu(self, menu_id, menu_title, before_menu_id):
        assert menu_id.endswith("_menu")
        assert before_menu_id.endswith("_menu") if before_menu_id is not None else True
        if not hasattr(self, "_" + menu_id):
            before_menu = getattr(self, "_" + before_menu_id) if before_menu_id is not None else None
            menu = self.insert_menu(menu_title, before_menu)
            setattr(self, "_" + menu_id, menu)
        return getattr(self, "_" + menu_id)

    def show_about_box(self):
        version_str = self.app.version_str if self.app else str()
        root_dir = os.path.dirname((os.path.dirname(os.path.abspath(__file__))))
        path_ascend_count = 2
        for i in range(path_ascend_count):
            root_dir = os.path.dirname(root_dir)
        class AboutDialog(Dialog.OkCancelDialog):
            def __init__(self, ui):
                super(AboutDialog, self).__init__(ui, include_cancel=False)
                row = self.ui.create_row_widget()
                logo_column = self.ui.create_column_widget()
                logo_button = self.ui.create_push_button_widget()
                logo_button.icon = CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/logo3.png"))
                logo_column.add_spacing(26)
                logo_column.add(logo_button)
                logo_column.add_stretch()
                column = self.ui.create_column_widget()

                def make_label_row(label: str):
                    row_one = self.ui.create_row_widget()
                    row_one.add_spacing(13)
                    row_one.add(self.ui.create_label_widget(label))
                    row_one.add_spacing(13)
                    row_one.add_stretch()
                    return row_one

                column.add_spacing(26)
                column.add(make_label_row("Nion Swift {0} {1}".format(version_str, root_dir)))
                column.add(make_label_row("Copyright 2012-2019 Nion Co. All Rights Reserved."))
                column.add_spacing(26)
                column.add(make_label_row(sys.base_prefix))
                conda_path = pathlib.Path(sys.base_prefix) / "conda-meta"
                if conda_path.is_dir():
                    needs_spacing = True
                    for package in sorted(path.stem for path in conda_path.glob("*.json")):
                        if any(s in package for s in ["nion", "python", "scipy", "numpy", "pytz", "h5py"]):
                            if needs_spacing:
                                column.add_spacing(26)
                                needs_spacing = False
                            column.add(make_label_row(package))
                column.add_spacing(26)
                column.add_stretch()
                row.add(logo_column)
                row.add(column)
                self.content.add(row)

        about_dialog = AboutDialog(self.ui)
        about_dialog.show()

        self.__dialogs.append(weakref.ref(about_dialog))

    def find_dock_widget(self, dock_widget_id):
        """ Return the dock widget by id. """
        return self.workspace_controller._find_dock_widget(dock_widget_id)

    def add_periodic(self, interval: float, listener_fn):
        """Add a listener function and return listener token. Token can be closed or deleted to unlisten."""
        class PeriodicListener:
            def __init__(self, interval: float, listener_fn):
                self.interval = interval
                self.__listener_fn = listener_fn
                # the call function is very performance critical; make it fast by using a property
                # instead of a logic statement each time.
                if callable(listener_fn):
                    self.call = self.__listener_fn
                else:
                    def void(*args, **kwargs):
                        pass
                    self.call = void
                self.next_scheduled_time = time.time() + interval
            def close(self):
                self.__listener_fn = None
                def void(*args, **kwargs):
                    pass
                self.call = void
        listener = PeriodicListener(interval, listener_fn)
        def remove_listener(weak_listener):
            with self.__weak_periodic_listeners_mutex:
                self.__weak_periodic_listeners.remove(weak_listener)
        weak_listener = weakref.ref(listener, remove_listener)
        with self.__weak_periodic_listeners_mutex:
            self.__weak_periodic_listeners.append(weak_listener)
        return listener

    def periodic(self):
        with self.__weak_periodic_listeners_mutex:
            periodic_listeners = copy.copy(self.__weak_periodic_listeners)
        current_time = time.time()
        for weak_periodic_listener in periodic_listeners:
            periodic_listener = weak_periodic_listener()
            if periodic_listener and current_time >= periodic_listener.next_scheduled_time:
                try:
                    periodic_listener.call()
                except Exception as e:
                    import traceback
                    logging.debug("Event Error: %s", e)
                    traceback.print_exc()
                    traceback.print_stack()
                periodic_listener.next_scheduled_time = current_time + periodic_listener.interval
        super().periodic()
        self.document_model.perform_data_item_updates()
        if self.workspace_controller:
            self.workspace_controller.periodic()
        if self.__last_activity is not None and time.time() - self.__last_activity > 60 * 60:
            pass  # self.app.choose_library()

    @property
    def _undo_stack(self):
        return self.__undo_stack

    @property
    def last_undo_command(self) -> typing.Optional[Undo.UndoableCommand]:
        return self.__undo_stack.last_command

    def push_undo_command(self, undo_command: Undo.UndoableCommand) -> None:
        if undo_command:
            self.__undo_stack.push(undo_command)
        else:
            self.__undo_stack.clear()

    def pop_undo_command(self) -> typing.Optional[Undo.UndoableCommand]:
        return self.__undo_stack.pop_command()

    @property
    def workspace_controller(self):
        return self.__workspace_controller

    @property
    def workspace(self):
        return self.__workspace_controller

    def refocus_widget(self, widget):
        display_panel = self.selected_display_panel
        if display_panel:
            display_panel.request_focus()
        else:
            super().refocus_widget(widget)

    def request_refocus(self):
        display_panel = self.selected_display_panel
        if display_panel:
            display_panel.request_focus()

    @property
    def display_items_model(self):
        return self.__display_items_model

    @property
    def filtered_display_items_model(self):
        return self.__filtered_display_items_model

    def __update_display_items_model(self, display_items_model: ListModel.FilteredListModel, data_group: typing.Optional[DataGroup.DataGroup], filter_id: typing.Optional[str]) -> None:
        """Update the data item model with a new container, filter, and sorting.

        This is called when the data item model is created or when the user changes
        the data group or sorting settings.
        """

        with display_items_model.changes():  # change filter and sort together
            project_filter = self.document_model.profile.project_filter
            if data_group is not None:
                display_items_model.container = data_group
                display_items_model.filter = ListModel.AndFilter((project_filter, ListModel.Filter(True)))
                display_items_model.sort_key = None
                display_items_model.filter_id = None
            elif filter_id == "latest-session":
                display_items_model.container = self.document_model
                display_items_model.filter = ListModel.AndFilter((project_filter, ListModel.EqFilter("session_id", self.document_model.session_id)))
                display_items_model.sort_key = DataItem.sort_by_date_key
                display_items_model.sort_reverse = True
                display_items_model.filter_id = filter_id
            elif filter_id == "temporary":
                display_items_model.container = self.document_model
                display_items_model.filter = ListModel.AndFilter((project_filter, ListModel.NotEqFilter("category", "persistent")))
                display_items_model.sort_key = DataItem.sort_by_date_key
                display_items_model.sort_reverse = True
                display_items_model.filter_id = filter_id
            elif filter_id == "persistent":
                display_items_model.container = self.document_model
                display_items_model.filter = ListModel.AndFilter((project_filter, ListModel.EqFilter("category", "persistent")))
                display_items_model.sort_key = DataItem.sort_by_date_key
                display_items_model.sort_reverse = True
                display_items_model.filter_id = filter_id
            elif filter_id == "none":  # not intended to be used directly
                display_items_model.container = self.document_model
                display_items_model.filter = ListModel.AndFilter((project_filter, ListModel.Filter(False)))
                display_items_model.sort_key = DataItem.sort_by_date_key
                display_items_model.sort_reverse = True
                display_items_model.filter_id = filter_id
            else:  # "all"
                display_items_model.container = self.document_model
                display_items_model.filter = project_filter
                display_items_model.sort_key = DataItem.sort_by_date_key
                display_items_model.sort_reverse = True
                display_items_model.filter_id = None

    def create_display_items_model(self, data_group, filter_id):
        display_items_model = ListModel.FilteredListModel(items_key="display_items")
        self.__update_display_items_model(display_items_model, data_group, filter_id)
        return display_items_model

    def set_data_group(self, data_group):
        if self.__display_items_model is not None:
            container = data_group if data_group else self.document_model
            if container != self.__display_items_model.container:
                self.__update_display_items_model(self.__display_items_model, data_group, self.__display_items_model.filter_id)
                self.filter_changed_event.fire(data_group, self.__display_items_model.filter_id)

    def set_filter(self, filter_id):
        if self.__display_items_model is not None:
            if filter_id != self.__display_items_model.filter_id:
                self.__update_display_items_model(self.__display_items_model, None, filter_id)
                self.filter_changed_event.fire(None, filter_id)

    def get_data_group_and_filter_id(self):
        # used for display panel initialization
        data_group = self.__display_items_model.container if self.__display_items_model.container != self.document_model else None
        filter_id = self.__display_items_model.filter_id
        return data_group, filter_id

    @property
    def display_filter(self) -> ListModel.Filter:
        return self.__filtered_display_items_model.filter

    @display_filter.setter
    def display_filter(self, display_filter: ListModel.Filter) -> None:
        if self.__filtered_display_items_model is not None:  # during close
            self.__filtered_display_items_model.filter = display_filter

    @property
    def selected_display_items(self) -> typing.List[DisplayItem.DisplayItem]:
        selected_display_items = list()
        display_items = self.__filtered_display_items_model.display_items
        for index in self.selection.ordered_indexes:
            selected_display_items.append(display_items[index])
        return selected_display_items

    @property
    def selected_data_items(self) -> typing.List[DataItem.DataItem]:
        selected_display_items = list()
        for display_item in self.selected_display_items:
            for data_item in display_item.data_items:
                if not data_item in selected_display_items:
                    selected_display_items.append(data_item)
        return selected_display_items

    def select_display_items_in_data_panel(self, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
        filtered_display_items = self.filtered_display_items_model.display_items
        indexes = set()
        for index, display_item in enumerate(filtered_display_items):
            if display_item in display_items:
                indexes.add(index)
        self.selection.set_multiple(indexes)
        if len(display_items) > 0:
            display_item = display_items[0]
            if display_item in filtered_display_items:
                self.selection.anchor_index = filtered_display_items.index(display_item)

    def select_data_items_in_data_panel(self, data_items: typing.Sequence[DataItem.DataItem]) -> None:
        document_model = self.document_model
        associated_display_items = [document_model.get_display_item_for_data_item(data_item) for data_item in data_items]
        self.select_display_items_in_data_panel(associated_display_items)

    # track the selected data item. this can be called by ui elements when
    # they get focus. the selected data item will stay the same until another ui
    # element gets focus or the data item is removed from the document.
    def notify_focused_display_changed(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if self.__focused_display_item != display_item:
            self.__focused_display_item = display_item
            self.focused_display_item_changed_event.fire(display_item)

    @property
    def focused_data_item(self) -> typing.Optional[DataItem.DataItem]:
        """Return the data item with keyboard focus."""
        return self.__focused_display_item.data_item if self.__focused_display_item else None

    @property
    def focused_display_item(self) -> DisplayItem.DisplayItem:
        """Return the display with keyboard focus."""
        return self.__focused_display_item

    def select_data_item_in_data_panel(self, data_item: DataItem.DataItem) -> None:
        """Select the data item in the data panel."""
        self.select_data_items_in_data_panel([data_item] if data_item else [])

    def select_data_group_in_data_panel(self, data_group: DataGroup.DataGroup, data_item: DataItem.DataItem=None) -> None:
        # used for testing only
        self.set_data_group(data_group)
        self.select_data_item_in_data_panel(data_item)

    def select_filter_in_data_panel(self, filter_id: str) -> None:
        # used for testing only
        self.set_filter(filter_id)

    @property
    def selected_display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        """Return the selected display item.

        The selected display is the display ite that has keyboard focus in the data panel or a display panel.
        """
        # first check for the [focused] data browser
        display_item = self.focused_display_item
        if not display_item:
            selected_display_panel = self.selected_display_panel
            display_item = selected_display_panel.display_item if selected_display_panel else None
        return display_item

    @property
    def selected_data_item(self) -> typing.Optional[DataItem.DataItem]:
        selected_display_item = self.selected_display_item
        return selected_display_item.data_item if selected_display_item else None

    def delete_display_items(self, display_items: typing.Sequence[DisplayItem.DisplayItem], container=None) -> None:
        container = container if container else self.__display_items_model.container
        if container is self.document_model:
            if display_items:
                command = self.create_remove_display_items_command(display_items)
                command.perform()
                self.push_undo_command(command)
        elif isinstance(container, DataGroup.DataGroup):
            if display_items:
                command = DocumentController.RemoveDataGroupDisplayItemsCommand(self.document_model, container, display_items)
                command.perform()
                self.push_undo_command(command)

    def register_display_panel(self, display_panel):
        pass

    def unregister_display_panel(self, display_panel):
        if self.selected_display_panel == display_panel:
            self.selected_display_panel = None

    @property
    def selected_display_panel(self):
        return self.__weak_selected_display_panel() if self.__weak_selected_display_panel else None

    @selected_display_panel.setter
    def selected_display_panel(self, selected_display_panel):
        weak_selected_display_panel = weakref.ref(selected_display_panel) if selected_display_panel else None
        if weak_selected_display_panel != self.__weak_selected_display_panel:
            # save the selected panel
            self.__weak_selected_display_panel = weak_selected_display_panel
            # tell the workspace the selected image panel changed so that it can update the focus/selected rings
            self.workspace_controller.selected_display_panel_changed(self.selected_display_panel)
            # notify listeners that the data item has changed. in this case, a changing data item
            # means that which selected data item is selected has changed.
            display_item = selected_display_panel.display_item if selected_display_panel else None
            self.notify_focused_display_changed(display_item)

    def next_result_display_panel(self):
        for display_panel in self.workspace.display_panels:
            if display_panel.is_result_panel:
                return display_panel
        return None

    # this can be called from any user interface element that wants to update the cursor info
    # in the data panel. this would typically be from the image or line plot canvas.
    def cursor_changed(self, text_items: typing.List[str]) -> None:
        self.cursor_changed_event.fire(text_items)

    @property
    def tool_mode(self):
        return self.__tool_mode

    @tool_mode.setter
    def tool_mode(self, tool_mode):
        self.__tool_mode = tool_mode
        self.tool_mode_changed_event.fire(tool_mode)

    def new_window_with_data_item(self, workspace_id, display_item=None):
        # hack to work around Application <-> DocumentController interdependency.
        self.create_new_document_controller_event.fire(self.document_model, workspace_id, display_item)

    def __handle_new_project(self) -> None:
        class NewProjectDialog(Dialog.ActionDialog):

            def __init__(self, ui, app, parent_window, profile: Profile.Profile):
                super().__init__(ui, title=_("New Project"), app=app, persistent_id="new_project_dialog")

                self._create_menus()

                self.directory = self.ui.get_persistent_string("project_directory", self.ui.get_document_location())

                project_base_name = _("Nion Swift Project") + " " + datetime.datetime.now().strftime("%Y%m%d")
                project_base_index = 0
                project_base_index_str = ""
                while os.path.exists(os.path.join(self.directory, project_base_name + project_base_index_str)):
                    project_base_index += 1
                    project_base_index_str = " " + str(project_base_index)

                self.project_name = project_base_name + project_base_index_str

                def safe_request_close():
                    parent_window.queue_task(self.request_close)

                def handle_new():
                    self.project_name = self.__project_name_field.text
                    profile.create_project(pathlib.Path(self.directory), self.project_name)
                    return True

                def handle_new_and_close():
                    handle_new()
                    safe_request_close()
                    return True

                column = self.ui.create_column_widget()

                directory_header_row = self.ui.create_row_widget()
                directory_header_row.add_spacing(13)
                directory_header_row.add(self.ui.create_label_widget(_("Projects Folder: "), properties={"font": "bold"}))
                directory_header_row.add_stretch()
                directory_header_row.add_spacing(13)

                show_directory_row = self.ui.create_row_widget()
                show_directory_row.add_spacing(26)
                directory_label = self.ui.create_label_widget(self.directory)
                show_directory_row.add(directory_label)
                show_directory_row.add_stretch()
                show_directory_row.add_spacing(13)

                choose_directory_row = self.ui.create_row_widget()
                choose_directory_row.add_spacing(26)
                choose_directory_button = self.ui.create_push_button_widget(_("Choose..."))
                choose_directory_row.add(choose_directory_button)
                choose_directory_row.add_stretch()
                choose_directory_row.add_spacing(13)

                project_name_header_row = self.ui.create_row_widget()
                project_name_header_row.add_spacing(13)
                project_name_header_row.add(self.ui.create_label_widget(_("Project Name: "), properties={"font": "bold"}))
                project_name_header_row.add_stretch()
                project_name_header_row.add_spacing(13)

                project_name_row = self.ui.create_row_widget()
                project_name_row.add_spacing(26)
                project_name_field = self.ui.create_line_edit_widget(properties={"width": 400})
                project_name_field.text = self.project_name
                project_name_field.on_return_pressed = handle_new_and_close
                project_name_field.on_escape_pressed = safe_request_close
                project_name_row.add(project_name_field)
                project_name_row.add_stretch()
                project_name_row.add_spacing(13)

                column.add_spacing(12)
                column.add(directory_header_row)
                column.add_spacing(8)
                column.add(show_directory_row)
                column.add_spacing(8)
                column.add(choose_directory_row)
                column.add_spacing(16)
                column.add(project_name_header_row)
                column.add_spacing(8)
                column.add(project_name_row)
                column.add_stretch()
                column.add_spacing(16)

                def choose() -> None:
                    existing_directory, directory = self.ui.get_existing_directory_dialog(_("Choose Project Directory"), self.directory)
                    if existing_directory:
                        self.directory = existing_directory
                        directory_label.text = self.directory
                        self.ui.set_persistent_string("project_directory", self.directory)

                choose_directory_button.on_clicked = choose

                self.add_button(_("Cancel"), lambda: True)
                self.add_button(_("Create Project"), handle_new)

                self.content.add(column)

                self.__project_name_field = project_name_field

            def show(self):
                super().show()
                self.__project_name_field.focused = True

        new_project_dialog = NewProjectDialog(self.ui, self.app, self, self.document_model.profile)
        new_project_dialog.show()

    def __handle_open_project(self) -> None:
        filter = "Projects (*.nsproj);;Legacy Libraries (*.nslib);;All Files (*.*)"
        import_dir = self.ui.get_persistent_string("open_directory", self.ui.get_document_location())
        paths, selected_filter, selected_directory = self.get_file_paths_dialog(_("Add Existing Library"), import_dir, filter)
        self.ui.set_persistent_string("open_directory", selected_directory)
        if len(paths) == 1:
            self.document_model.profile.open_project(pathlib.Path(paths[0]))

    def __handle_upgrade_project(self) -> None:
        for project in self.document_model.profile.selected_projects_model.value:
            self.document_model.profile.upgrade_project(project)

    def __handle_remove_project(self) -> None:
        for project in self.document_model.profile.selected_projects_model.value:
            self.document_model.profile.remove_project(project)

    def __set_work_project(self) -> None:
        projects = self.document_model.profile.selected_projects_model.value
        if not projects:
            raise Exception("Select a project in the project panel.")
        if len(projects) > 1:
            raise Exception("Select a single project in the project panel.")
        self.document_model.profile.set_work_project(projects[0])

    def toggle_project_active(self, project: Project.Project) -> None:
        self.document_model.profile.toggle_project_active(project)
        self.__display_items_model.mark_changed()
        self.active_projects_changed_event.fire()

    def __import_folder(self):
        documents_dir = self.ui.get_document_location()
        workspace_dir, directory = self.ui.get_existing_directory_dialog(_("Choose Image Folder"), documents_dir)
        absolute_file_paths = set()
        for root, dirs, files in os.walk(workspace_dir):
            absolute_file_paths.update([os.path.join(root, data_file) for data_file in files])
        readable_file_paths = list()
        readers = ImportExportManager.ImportExportManager().get_readers()
        for file_path in absolute_file_paths:
            root, extension = os.path.splitext(file_path)
            for reader in readers:
                if extension[1:] in reader.extensions:
                    readable_file_paths.append(file_path)
                    break  # skip other readers
        self.receive_files(readable_file_paths)

    def import_file(self):
        # present a loadfile dialog to the user
        readers = ImportExportManager.ImportExportManager().get_readers()
        all_extensions = []
        for reader_extension_list in [reader.extensions for reader in readers]:
            all_extensions.extend(reader_extension_list)
        filter = "All Readable Files (" + " ".join(["*."+extension for extension in all_extensions]) + ")"
        filter += ";;" + ";;".join(
            [reader.name + " files (" + " ".join(
                ["*."+extension for extension in reader.extensions])
             + ")" for reader in readers])
        filter += ";;All Files (*.*)"
        import_dir = self.ui.get_persistent_string("import_directory", "")
        paths, selected_filter, selected_directory = self.get_file_paths_dialog(_("Import File(s)"), import_dir, filter)
        self.ui.set_persistent_string("import_directory", selected_directory)
        self.receive_files(paths, display_panel=self.next_result_display_panel())

    def export_file(self, display_item: DisplayItem.DisplayItem) -> None:
        # present a loadfile dialog to the user
        data_item = display_item.data_item
        writers = ImportExportManager.ImportExportManager().get_writers_for_data_item(data_item)
        name_writer_dict = dict()
        for writer in writers:
            writer_key = (writer.name, " ".join(["*." + extension for extension in writer.extensions]))
            name_writer_dict.setdefault(writer_key, writer)
        # make a list of tuples (writer name, writer extensions, writer) from the name_writer_dict
        name_writer_list = (key + (name_writer_dict[key],) for key in sorted(name_writer_dict.keys()))
        filter_line_to_writer_map = dict()
        filter_lines = list()
        for writer_name, writer_extensions, writer in name_writer_list:
            filter_line = writer_name + " files (" + writer_extensions + ")"
            filter_lines.append(filter_line)
            filter_line_to_writer_map[filter_line] = writer
        filter = ";;".join(filter_lines)
        filter += ";;All Files (*.*)"
        export_dir = self.ui.get_persistent_string("export_directory", self.ui.get_document_location())
        export_dir = os.path.join(export_dir, data_item.title)
        selected_filter = self.ui.get_persistent_string("export_filter")
        path, selected_filter, selected_directory = self.get_save_file_path(_("Export File"), export_dir, filter, selected_filter)
        selected_writer = filter_line_to_writer_map.get(selected_filter)
        if path and not os.path.splitext(path)[1]:
            if selected_writer:
                path = path + os.path.extsep + selected_writer.extensions[0]
        if selected_writer and path:
            self.ui.set_persistent_string("export_directory", selected_directory)
            self.ui.set_persistent_string("export_filter", selected_filter)
            ImportExportManager.ImportExportManager().write_display_item_with_writer(self.ui, selected_writer, display_item, path)

    def export_files(self, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
        if len(display_items) > 1:
            export_dialog = ExportDialog.ExportDialog(self.ui)
            export_dialog.on_accept = functools.partial(export_dialog.do_export, display_items)
            export_dialog.show()
            self.__dialogs.append(weakref.ref(export_dialog))
        elif len(display_items) == 1:
            self.export_file(display_items[0])

    def export_svg(self, display_item: DisplayItem.DisplayItem) -> None:
        filter = "SVG File (*.svg);;All Files (*.*)"
        export_dir = self.ui.get_persistent_string("export_directory", self.ui.get_document_location())
        export_dir = os.path.join(export_dir, display_item.displayed_title)
        path, selected_filter, selected_directory = self.get_save_file_path(_("Export File"), export_dir, filter, None)
        if path and not os.path.splitext(path)[1]:
            path = path + os.path.extsep + "svg"
        if path:
            self.ui.set_persistent_string("export_directory", selected_directory)
            FontMetrics = collections.namedtuple("FontMetrics", ["width", "height", "ascent", "descent", "leading"])

            def get_font_metrics(font, text):
                return FontMetrics(width=6.5 * len(text), height=15, ascent=12, descent=3, leading=0)

            if display_item.display_data_shape and len(display_item.display_data_shape) == 2:
                display_shape = Geometry.IntSize(height=800, width=800)
            else:
                display_shape = Geometry.IntSize(height=600, width=800)

            drawing_context, shape = DisplayPanel.preview(get_font_metrics, display_item, display_shape.width, display_shape.height)

            view_box = Geometry.IntRect(Geometry.IntPoint(), shape)

            svg = drawing_context.to_svg(shape, view_box)

            temp_filepath = path + ".temp"
            with open(temp_filepath, "w") as fp:
                fp.write(svg)
            os.replace(temp_filepath, path)

    # this method creates a task. it is thread safe.
    def create_task_context_manager(self, title, task_type, logging=True):
        task = Task.Task(title, task_type)  # NOTE: currently, tasks don't get deleted since they are displayed until exit.
        task_context_manager = Task.TaskContextManager(self, task, logging)
        self.task_created_event.fire(task)
        return task_context_manager

    def is_dialog_type_open(self, dialog_class) -> bool:
        for dialog_weakref in self.__dialogs:
            if isinstance(dialog_weakref(), dialog_class):
                return True
        return False

    def register_dialog(self, dialog: Window.Window) -> None:
        def close_preferences():
            self.__dialogs.remove(weakref.ref(dialog))
        dialog.on_close = close_preferences
        self.__dialogs.append(weakref.ref(dialog))

    def open_preferences(self):
        if not self.is_dialog_type_open(PreferencesDialog.PreferencesDialog):
            preferences_dialog = PreferencesDialog.PreferencesDialog(self.ui, self.app)
            preferences_dialog.show()
            self.register_dialog(preferences_dialog)

    def new_interactive_script_dialog(self):
        interactive_dialog = ScriptsDialog.RunScriptDialog(self)
        interactive_dialog.show()
        self.register_dialog(interactive_dialog)

    def new_console_dialog(self):
        console_dialog = ConsoleDialog.ConsoleDialog(self)
        console_dialog.show()
        self.register_dialog(console_dialog)

    def new_edit_computation_dialog(self, data_item=None):
        if not data_item:
            data_item = self.selected_data_item
        if data_item:
            edit_computation_dialog = ComputationPanel.EditComputationDialog(self, data_item)
            edit_computation_dialog.show()
            self.register_dialog(edit_computation_dialog)

    def new_display_editor_dialog(self, display_item: DisplayItem.DisplayItem=None):
        if not display_item:
            display_item = self.selected_display_item
        if display_item:
            edit_display_dialog = DisplayEditorPanel.DisplayEditorDialog(self, display_item)
            edit_display_dialog.show()
            self.register_dialog(edit_display_dialog)

    def new_recorder_dialog(self, data_item=None):
        if not data_item:
            data_item = self.selected_data_item
        if data_item:
            recorder_dialog = RecorderPanel.RecorderDialog(self, data_item)
            recorder_dialog.show()
            self.register_dialog(recorder_dialog)

    def __deep_copy(self):
        self._dispatch_any_to_focus_widget("handle_deep_copy")

    def handle_undo(self):
        if self.__undo_stack.can_undo:
            self.__undo_stack.undo()

    def get_undo_menu_item_state(self):
        self.__undo_stack.validate()
        return UserInterface.MenuItemState(title=self.__undo_stack.undo_title, enabled=self.__undo_stack.can_undo, checked=False)

    def handle_redo(self):
        if self.__undo_stack.can_redo:
            self.__undo_stack.redo()

    def get_redo_menu_item_state(self):
        return UserInterface.MenuItemState(title=self.__undo_stack.redo_title, enabled=self.__undo_stack.can_redo, checked=False)

    def handle_copy(self):
        self.copy_selected_graphics()

    def handle_cut(self):
        self.copy_selected_graphics()
        self.remove_selected_graphics()

    def handle_paste(self):
        display_item = self.selected_display_item
        if display_item:
            mime_data = self.ui.clipboard_mime_data()
            graphics = MimeTypes.mime_data_get_graphics(mime_data)
            if graphics:
                display_item.graphic_selection.clear()
                command = DisplayPanel.InsertGraphicsCommand(self, display_item, graphics)
                command.perform()
                self.push_undo_command(command)
                for graphic in graphics:
                    display_item.graphic_selection.add(display_item.graphics.index(graphic))
                return True
            display_item_to_paste = MimeTypes.mime_data_get_display_item(mime_data, self.document_model)
            data_item_to_paste = display_item_to_paste.data_item if display_item else None
            if data_item_to_paste:
                command = DisplayPanel.AppendDisplayDataChannelCommand(self.document_model, display_item, data_item_to_paste)
                command.perform()
                self.push_undo_command(command)
        return False

    def handle_delete(self):
        # delete key gets handled by key handlers, but this method gets called by menu items
        self.remove_selected_graphics()

    class InsertDataGroupDisplayItemCommand(Undo.UndoableCommand):
        def __init__(self, document_model, data_group: DataGroup.DataGroup, before_index: int, display_item: DisplayItem.DisplayItem):
            super().__init__("Insert Data Item")
            self.__document_model = document_model
            self.__data_group_proxy = data_group.create_proxy()
            self.__before_index = before_index
            self.__display_item_proxy = display_item.create_proxy()
            self.initialize()

        def close(self):
            self.__document_model = None
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            self.__before_index = None
            self.__display_item_proxy.close()
            self.__display_item_proxy = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__data_group_proxy.item
            return data_group.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__data_group_proxy.item
            data_group.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            data_group = self.__data_group_proxy.item
            display_item = self.__display_item_proxy.item
            data_group.insert_display_item(self.__before_index, display_item)

        def _undo(self) -> None:
            data_group = self.__data_group_proxy.item
            data_group.remove_display_item(data_group.display_items[self.__before_index])

        def _redo(self) -> None:
            self.perform()

    def create_insert_data_group_display_item_command(self, data_group: DataGroup.DataGroup, before_index: int, display_item: DisplayItem.DisplayItem) -> InsertDataGroupDisplayItemCommand:
        return DocumentController.InsertDataGroupDisplayItemCommand(self.document_model, data_group, before_index, display_item)

    class InsertDataGroupDataItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_controller: "DocumentController", data_group: DataGroup.DataGroup, data_items: typing.Sequence[DataItem.DataItem], index: int):
            super().__init__("Insert Data Items")
            self.__document_controller = document_controller
            self.__data_group_proxy = data_group.create_proxy()
            self.__data_group_indexes = list()
            self.__data_group_display_item_proxies = list()
            self.__data_items = data_items  # only in perform
            self.__display_item_index = index
            self.__display_item_indexes = list()
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__data_group_indexes = None
            for display_item_proxy in self.__data_group_display_item_proxies:
                display_item_proxy.close()
            self.__data_group_display_item_proxies = None
            self.__display_item_index = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__data_group_proxy.item
            return self.__document_controller.document_model.modified_state, data_group.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__data_group_proxy.item
            self.__document_controller.document_model.modified_state, data_group.modified_state = modified_state

        def perform(self):
            document_model = self.__document_controller.document_model
            data_group = self.__data_group_proxy.item
            index = self.__display_item_index
            display_items = list()
            for data_item in self.__data_items:
                document_model.append_data_item(data_item)
                self.__display_item_indexes.append(len(document_model.display_items))
                display_items.append(document_model.get_display_item_for_data_item(data_item))
            for display_item in display_items:
                if not display_item in data_group.display_items:
                    data_group.insert_display_item(index, display_item)
                    self.__data_group_indexes.append(index)
                    self.__data_group_display_item_proxies.append(display_item.project.create_item_proxy(item=display_item))
                    index += 1
            self.__display_items = None

        def _undo(self) -> None:
            document_model = self.__document_controller.document_model
            data_group = self.__data_group_proxy.item
            display_items = [data_group.display_items[index] for index in self.__data_group_indexes]
            for display_item in display_items:
                if display_item in data_group.display_items:
                    data_group.remove_display_item(display_item)
            display_items = [document_model.display_items[index] for index in self.__display_item_indexes]
            for display_item in display_items:
                if display_item in document_model.display_items:
                    self.__undelete_logs.append(document_model.remove_display_item_with_log(display_item, safe=True))

        def _redo(self) -> None:
            data_group = self.__data_group_proxy.item
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            index = self.__display_item_index
            display_items = [display_item_proxy.item for display_item_proxy in reversed(self.__data_group_display_item_proxies)]
            for display_item in display_items:
                if not display_item in data_group.display_items:
                    data_group.insert_display_item(index, display_item)

    class RemoveDataGroupDisplayItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_model, data_group: DataGroup.DataGroup, display_items: typing.Sequence[DisplayItem.DisplayItem]):
            super().__init__("Remove Data Item")
            self.__document_model = document_model
            self.__data_group_proxy = data_group.create_proxy()
            combined = [(data_group.display_items.index(display_item), display_item) for display_item in display_items]
            combined = sorted(combined, key=operator.itemgetter(0), reverse=True)
            self.__display_item_indexes = list(map(operator.itemgetter(0), combined))
            self.__display_item_proxies = [display_item.create_proxy() for index, display_item in combined]
            self.initialize()

        def close(self):
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            for display_item_proxy in self.__display_item_proxies:
                display_item_proxy.close()
            self.__display_item_proxies = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__data_group_proxy.item
            return data_group.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__data_group_proxy.item
            data_group.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            data_group = self.__data_group_proxy.item
            display_items = [data_group.display_items[index] for index in self.__display_item_indexes]
            for display_item in display_items:
                if display_item in data_group.display_items:
                    data_group.remove_display_item(display_item)

        def _undo(self) -> None:
            data_group = self.__data_group_proxy.item
            display_items = [display_item_proxy.item for display_item_proxy in self.__display_item_proxies]
            for index, display_item in zip(self.__display_item_indexes, display_items):
                data_group.insert_display_item(index, display_item)

        def _redo(self) -> None:
            self.perform()

    class RenameDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model, data_group: DataGroup.DataGroup, title: str):
            super().__init__("Rename Data Group")
            self.__document_model = document_model
            self.__data_group_proxy = data_group.create_proxy()
            self.__title = title
            self.__new_title = None
            self.initialize()

        def close(self):
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__data_group_proxy.item
            return data_group.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__data_group_proxy.item
            data_group.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            data_group = self.__data_group_proxy.item
            self.__new_title = data_group.title
            data_group.title = self.__title

        def _undo(self) -> None:
            data_group = self.__data_group_proxy.item
            data_group.title = self.__new_title

        def _redo(self) -> None:
            self.perform()

    def create_rename_data_group_command(self, data_group: DataGroup.DataGroup, title: str) -> RenameDataGroupCommand:
        return DocumentController.RenameDataGroupCommand(self.document_model, data_group, title)

    class InsertDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model, container: typing.Union[DataGroup.DataGroup, DocumentModel.DocumentModel], before_index: int, data_group: DataGroup.DataGroup):
            super().__init__("Insert Data Group")
            self.__document_model = document_model
            self.__container_proxy = container.create_proxy()
            self.__before_index = before_index
            self.__data_group_properties = data_group.write_to_dict()
            self.__data_group_proxy = None
            self.initialize()

        def close(self):
            if self.__data_group_proxy:
                self.__data_group_proxy.close()
                self.__data_group_proxy = None
            self.__container_proxy.close()
            self.__container_proxy = None
            super().close()

        def _get_modified_state(self):
            container = self.__container_proxy.item
            return container.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            container = self.__container_proxy.item
            container.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            container = self.__container_proxy.item
            data_group = DataGroup.DataGroup()
            data_group.read_from_dict(self.__data_group_properties)
            container.insert_data_group(self.__before_index, data_group)
            self.__data_group_proxy = data_group.create_proxy()

        def _undo(self) -> None:
            container = self.__container_proxy.item
            data_group = self.__data_group_proxy.item
            container.remove_data_group(data_group)
            self.__data_group_proxy.close()
            self.__data_group_proxy = None

        def _redo(self) -> None:
            self.perform()

    def create_insert_data_group_command(self, container: typing.Union[DataGroup.DataGroup, DocumentModel.DocumentModel], before_index: int, data_group: DataGroup.DataGroup) -> InsertDataGroupCommand:
        return DocumentController.InsertDataGroupCommand(self.document_model, container, before_index, data_group)

    class RemoveDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model, container: typing.Union[DataGroup.DataGroup, DocumentModel.DocumentModel], data_group: DataGroup.DataGroup):
            super().__init__("Remove Data Group")
            self.__document_model = document_model
            self.__container_proxy = container.create_proxy()
            self.__data_group_proxy = data_group.create_proxy()
            self.__data_group_properties = None
            self.__data_group_index = None
            self.initialize()

        def close(self):
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            self.__container_proxy.close()
            self.__container_proxy = None
            super().close()

        def _get_modified_state(self):
            container = self.__container_proxy.item
            return container.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            container = self.__container_proxy.item
            container.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            container = self.__container_proxy.item
            data_group = self.__data_group_proxy.item
            self.__data_group_properties = data_group.write_to_dict()
            self.__data_group_index = container.data_groups.index(data_group)
            container.remove_data_group(data_group)

        def _undo(self) -> None:
            container = self.__container_proxy.item
            data_group = DataGroup.DataGroup()
            data_group.begin_reading()
            data_group.read_from_dict(self.__data_group_properties)
            data_group.finish_reading()
            container.insert_data_group(self.__data_group_index, data_group)

        def _redo(self) -> None:
            self.perform()

    def add_group(self):
        data_group = DataGroup.DataGroup()
        data_group.title = _("Untitled Group")
        command = DocumentController.InsertDataGroupCommand(self.document_model, self.document_model, 0, data_group)
        command.perform()
        self.push_undo_command(command)

    def remove_data_group_from_container(self, data_group, container):
        data_group_empty = len(data_group.display_items) == 0 and len(data_group.data_groups) == 0
        if data_group_empty:
            assert data_group in container.data_groups
            command = DocumentController.RemoveDataGroupCommand(self.document_model, container, data_group)
            command.perform()
            self.push_undo_command(command)

    def add_line_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.LineGraphic()
            graphic.start = (0.2, 0.2)
            graphic.end = (0.8, 0.8)
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_rectangle_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_ellipse_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.EllipseGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_point_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.PointGraphic()
            graphic.position = (0.5,0.5)
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_interval_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.IntervalGraphic()
            graphic.start = 0.25
            graphic.end = 0.75
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_channel_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.ChannelGraphic()
            graphic.position = 0.5
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_spot_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.SpotGraphic()
            graphic.bounds = Geometry.FloatRect.from_center_and_size((0.25, 0.25), (0.25, 0.25))
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_angle_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.WedgeGraphic()
            graphic.start_angle = 0
            graphic.end_angle = (3/4) * math.pi
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_band_pass_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.RingGraphic()
            graphic.radius_1 = 0.15
            graphic.radius_2 = 0.25
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_lattice_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.LatticeGraphic()
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def __change_graphics_role(self, role: typing.Optional[str]) -> bool:
        display_item = self.selected_display_item
        if display_item:
            if display_item.graphic_selection.has_selection:
                graphics = [display_item.graphics[index] for index in display_item.graphic_selection.indexes]
                graphics = itertools.filterfalse(lambda graphic: isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)), graphics)
                if graphics:
                    command = DisplayPanel.ChangeGraphicsCommand(self.document_model, display_item, graphics, command_id="change_role", is_mergeable=True, role=role)
                    command.perform()
                    self.push_undo_command(command)
                    return True
        return False

    def add_graphic_mask(self) -> bool:
        return self.__change_graphics_role("mask")

    def remove_graphic_mask(self) -> bool:
        return self.__change_graphics_role(None)

    def copy_selected_graphics(self):
        display_item = self.selected_display_item
        if display_item:
            mime_data = self.ui.create_mime_data()

            # copy the data item as an svg
            FontMetrics = collections.namedtuple("FontMetrics", ["width", "height", "ascent", "descent", "leading"])

            def get_font_metrics(_, text):
                return FontMetrics(width=6.5 * len(text), height=15, ascent=12, descent=3, leading=0)

            if display_item.display_data_shape and len(display_item.display_data_shape) == 2:
                display_shape = Geometry.IntSize(height=800, width=800)
            else:
                display_shape = Geometry.IntSize(height=600, width=800)

            drawing_context, shape = DisplayPanel.preview(get_font_metrics, display_item, display_shape.width,
                                                          display_shape.height)

            view_box = Geometry.IntRect(Geometry.IntPoint(), shape)

            svg = drawing_context.to_svg(shape, view_box)

            mime_data.set_data_as_string(MimeTypes.SVG_MIME_TYPE, svg)

            if display_item.graphic_selection.has_selection:
                # copy the graphic on the selected display item
                graphics = [display_item.graphics[index] for index in display_item.graphic_selection.indexes]
                MimeTypes.mime_data_put_graphics(mime_data, graphics)
                self.ui.clipboard_set_mime_data(mime_data)
                return True
            else:
                # copy the selected display item if graphic is not selected
                MimeTypes.mime_data_put_display_item(mime_data, display_item)
                self.ui.clipboard_set_mime_data(mime_data)

        return False

    def remove_selected_graphics(self) -> None:
        display_item = self.selected_display_item
        if display_item:
            if display_item.graphic_selection.has_selection:
                graphics = [display_item.graphics[index] for index in display_item.graphic_selection.indexes]
                if graphics:
                    command = self.create_remove_graphics_command(display_item, graphics)
                    command.perform()
                    self.push_undo_command(command)

    class RemoveGraphicsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", display_item: DisplayItem.DisplayItem, graphics: typing.Sequence[Graphics.Graphic]):
            super().__init__(_("Remove Graphics"))
            self.__document_controller = document_controller
            self.__display_item_proxy = display_item.create_proxy()
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__graphic_indexes = [display_item.graphics.index(graphic) for graphic in graphics]
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__display_item_proxy.close()
            self.__display_item_proxy = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__graphic_indexes = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            display_item = self.__display_item_proxy.item
            graphics = [display_item.graphics[index] for index in self.__graphic_indexes]
            for graphic in graphics:
                self.__undelete_logs.append(display_item.remove_graphic(graphic, safe=True))

        def _get_modified_state(self):
            display_item = self.__display_item_proxy.item
            return display_item.modified_state, self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state):
            display_item = self.__display_item_proxy.item
            display_item.modified_state, self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _compare_modified_states(self, state1, state2) -> bool:
            # after inserting, a computation may be performed and change the document. this ensures that this
            # undo is still enabled after that happens.
            return True

    def create_remove_graphics_command(self, display_item, graphics):
        return DocumentController.RemoveGraphicsCommand(self, display_item, graphics)

    class RemoveDisplayItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", display_items: typing.Sequence[DisplayItem.DisplayItem]):
            super().__init__(_("Remove Display Items"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__display_item_indexes = [document_controller.document_model.display_items.index(display_item) for display_item in display_items]
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__display_item_indexes = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            document_model = self.__document_controller.document_model
            display_items = [document_model.display_items[index] for index in self.__display_item_indexes]
            for display_item in display_items:
                if display_item in document_model.display_items:
                    selected_display_items = self.__document_controller.selected_display_items
                    if display_item in selected_display_items:
                        selected_display_items.remove(display_item)
                    self.__undelete_logs.append(document_model.remove_display_item_with_log(display_item))
                    self.__document_controller.select_display_items_in_data_panel(selected_display_items)

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state):
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def create_remove_display_items_command(self, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> Undo.UndoableCommand:
        return DocumentController.RemoveDisplayItemsCommand(self, display_items)

    class RemoveDataItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", data_items: typing.Sequence[DataItem.DataItem]):
            super().__init__(_("Remove Data Items"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__data_item_indexes = [document_controller.document_model.data_items.index(data_item) for data_item in data_items]
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__data_item_indexes = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            document_model = self.__document_controller.document_model
            data_items = [document_model.data_items[index] for index in self.__data_item_indexes]
            for data_item in data_items:
                if data_item in document_model.data_items:
                    self.__undelete_logs.append(document_model.remove_data_item_with_log(data_item, safe=True))

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state):
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def create_remove_data_items_command(self, data_items: typing.Sequence[DataItem.DataItem]) -> Undo.UndoableCommand:
        return DocumentController.RemoveDataItemsCommand(self, data_items)

    def add_data_element(self, data_element, source_data_item=None):
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        if data_item:
            self.document_model.append_data_item(data_item)
        return data_item

    def add_data(self, data, title=None):
        data_element = { "data": data, "title": title }
        return self.add_data_element(data_element)

    def show_display_item(self, display_item: DisplayItem.DisplayItem, *, source_display_item=None, source_data_item=None, request_focus=True) -> None:
        result_display_panel = self.next_result_display_panel()
        if result_display_panel:
            result_display_panel.set_display_panel_display_item(display_item)
            if request_focus:
                result_display_panel.request_focus()
        self.select_display_items_in_data_panel([display_item])
        if request_focus:
            self.notify_focused_display_changed(display_item)
            inspector_panel = self.find_dock_widget("inspector-panel").panel
            if inspector_panel is not None:
                inspector_panel.request_focus = True

    def _perform_redimension(self, display_item: DisplayItem.DisplayItem, data_descriptor: DataAndMetadata.DataDescriptor) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = self.document_model.get_redimension_new(display_item, data_descriptor)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
            return command.data_item
        else:
            command.close()

    def _perform_squeeze(self, display_item: DisplayItem.DisplayItem) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = self.document_model.get_squeeze_new(display_item)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
            return command.data_item
        else:
            command.close()

    def __adjust_redimension_data_menu(self):
        for action in self.__data_menu_actions:
            self._processing_redimension_menu.remove_action(action)
        self.__data_menu_actions = list()
        selected_display_panel = self.selected_display_panel
        display_item = selected_display_panel.display_item
        data_item = display_item.data_item if display_item else None
        if data_item:

            def describe_data_descriptor(data_descriptor: DataAndMetadata.DataDescriptor, data_shape: typing.List[int]) -> str:
                if data_descriptor.is_sequence:
                    data_type_name = _("Sequence of {} ".format(data_shape[0]))
                    index = 1
                else:
                    data_type_name = str()
                    index = 0
                if data_descriptor.collection_dimension_count == 1:
                    data_type_name += _("Collection of ") + str(data_shape[index]) + " "
                    index += 1
                elif data_descriptor.collection_dimension_count == 2:
                    data_type_name += str(data_shape[index]) + "x" + str(data_shape[index + 1]) + _(" Collection of ")
                    index += 2
                if data_descriptor.datum_dimension_count == 1:
                    data_type_name += "Spectra of Length " + str(data_shape[index])
                elif data_descriptor.datum_dimension_count == 2:
                    data_type_name += "Images of Shape " + str(data_shape[index]) + "x" + str(data_shape[index + 1])
                return data_type_name

            # add (disabled) existing data type menu item
            data_type_name = describe_data_descriptor(data_item.xdata.data_descriptor, data_item.xdata.data_shape)
            action = self._processing_redimension_menu.add_menu_item(data_type_name, None)
            action.enabled = False
            self.__data_menu_actions.append(action)

            # add redimension menu items if available
            for is_sequence, collection_dims, data_dims in itertools.product((True, False), (0, 1, 2), (1, 2)):
                data_descriptor = DataAndMetadata.DataDescriptor(is_sequence, collection_dims, data_dims)
                if data_descriptor.expected_dimension_count == data_item.xdata.data_descriptor.expected_dimension_count and data_descriptor != data_item.xdata.data_descriptor:
                    data_type_name = describe_data_descriptor(data_descriptor, data_item.xdata.data_shape)
                    action = self._processing_redimension_menu.add_menu_item(_("Redimension to {}").format(data_type_name), functools.partial(self._perform_redimension, display_item, data_descriptor))
                    self.__data_menu_actions.append(action)

            # add squeeze menu item if available
            data_descriptor = data_item.xdata.data_descriptor
            data_shape = list(data_item.xdata.data_shape)
            if 1 in data_shape[data_descriptor.collection_dimension_index_slice] or 1 in data_shape[data_descriptor.sequence_dimension_index_slice] and len(data_shape[data_descriptor.datum_dimension_index_slice]) > 1 and data_shape[data_descriptor.datum_dimension_index_slice].count(1) > 0:
                if data_descriptor.is_sequence and data_shape[data_descriptor.sequence_dimension_index_slice] == 1:
                    data_descriptor.is_sequence = False
                    data_shape = data_shape[1:]
                while data_shape[data_descriptor.collection_dimension_index_slice].count(1) > 0:
                    index = data_shape[data_descriptor.collection_dimension_index_slice].index(1)
                    del data_shape[data_descriptor.collection_dimension_index_slice.start + index]
                    data_descriptor.collection_dimension_count -= 1
                while len(data_shape[data_descriptor.datum_dimension_index_slice]) > 1 and data_shape[data_descriptor.datum_dimension_index_slice].count(1) > 0:
                    index = data_shape[data_descriptor.datum_dimension_index_slice].index(1)
                    del data_shape[data_descriptor.datum_dimension_index_slice.start + index]
                    data_descriptor.datum_dimension_count -= 1
                data_type_name = describe_data_descriptor(data_descriptor, data_shape)
                self.__data_menu_actions.append(self._processing_redimension_menu.add_menu_item(_("Squeeze to {}").format(data_type_name), functools.partial(self._perform_squeeze, display_item)))
        else:
            action = self._processing_redimension_menu.add_menu_item(_("No Data Selected"), None)
            action.enabled = False
            self.__data_menu_actions.append(action)
        self._window_menu_about_to_show()

    def __get_crop_graphic(self, display_item: DisplayItem.DisplayItem) -> typing.Optional[Graphics.Graphic]:
        crop_graphic = None
        data_item = display_item.data_item if display_item else None
        current_index = display_item.graphic_selection.current_index if display_item else None
        graphic = display_item.graphics[current_index] if current_index is not None else None
        if data_item and graphic:
            if data_item.is_datum_1d and isinstance(graphic, Graphics.IntervalGraphic):
                crop_graphic = graphic
            elif data_item.is_datum_2d and isinstance(graphic, Graphics.RectangleTypeGraphic):
                crop_graphic = graphic
        return crop_graphic

    def __get_mask_graphics(self, display_item: DisplayItem.DisplayItem) -> typing.List[Graphics.Graphic]:
        mask_graphics = list()
        data_item = display_item.data_item if display_item else None
        if data_item and len(data_item.dimensional_shape) == 2:
            current_index = display_item.graphic_selection.current_index
            if current_index is not None:
                graphic = display_item.graphics[current_index]
                if hasattr(graphic, 'get_mask'):
                    mask_graphics.append(graphic)
        return mask_graphics

    def processing_fft(self) -> DisplayItem.DisplayItem:
        return self.document_model.get_display_item_for_data_item(self.__processing_new(self.document_model.get_fft_new))

    def processing_ifft(self) -> DisplayItem.DisplayItem:
        return self.document_model.get_display_item_for_data_item(self.__processing_new(self.document_model.get_ifft_new))

    def processing_gaussian_blur(self) -> DisplayItem.DisplayItem:
        return self.document_model.get_display_item_for_data_item(self.__processing_new(self.document_model.get_gaussian_blur_new))

    def processing_resample(self) -> DisplayItem.DisplayItem:
        return self.document_model.get_display_item_for_data_item(self.__processing_new(self.document_model.get_resample_new))

    def processing_crop(self) -> DisplayItem.DisplayItem:
        return self.document_model.get_display_item_for_data_item(self.__processing_new(self.document_model.get_crop_new))

    def processing_slice(self) -> DisplayItem.DisplayItem:
        return self.document_model.get_display_item_for_data_item(self.__processing_new(self.document_model.get_slice_sum_new))

    def processing_projection(self) -> DisplayItem.DisplayItem:
        return self.document_model.get_display_item_for_data_item(self.__processing_new(self.document_model.get_projection_new))

    def processing_line_profile(self) -> DisplayItem.DisplayItem:
        return self.document_model.get_display_item_for_data_item(self.__processing_new(self.document_model.get_line_profile_new))

    def processing_invert(self) -> DisplayItem.DisplayItem:
        return self.document_model.get_display_item_for_data_item(self.__processing_new(self.document_model.get_invert_new))

    class InsertDataItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", data_item_fn: typing.Callable[[], DataItem.DataItem]):
            super().__init__(_("Insert Data Item"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__data_item_proxy = None
            self.__data_item_fn = data_item_fn
            self.__undelete_log = None
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__data_item_fn = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            if self.__undelete_log:
                self.__undelete_log.close()
                self.__undelete_log = None
            if self.__data_item_proxy:
                self.__data_item_proxy.close()
                self.__data_item_proxy = None
            super().close()

        def perform(self):
            data_item = self.__data_item_fn()
            self.__data_item_proxy = data_item.create_proxy() if data_item else None

        @property
        def data_item(self):
            return self.__data_item_proxy.item if self.__data_item_proxy else None

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # after inserting, a computation may be performed and change the document. this ensures that this
            # undo is still enabled after that happens.
            return True

        def _redo(self):
            self.__document_controller.document_model.undelete_all(self.__undelete_log)
            self.__undelete_log.close()
            self.__undelete_log = None
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self):
            data_item = self.data_item
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__undelete_log = self.__document_controller.document_model.remove_data_item_with_log(data_item, safe=True)
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

    def create_insert_data_item_command(self, data_item_fn: typing.Callable[[], DataItem.DataItem]) -> Undo.UndoableCommand:
        return DocumentController.InsertDataItemCommand(self, data_item_fn)

    def _perform_duplicate(self, data_item: DataItem.DataItem) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = self.document_model.copy_data_item(data_item)
            new_data_item.title = _("Clone of ") + data_item.title
            new_data_item.category = data_item.category
            self.select_data_item_in_data_panel(new_data_item)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.notify_focused_display_changed(new_display_item)
            inspector_panel = self.find_dock_widget("inspector-panel").panel
            if inspector_panel is not None:
                inspector_panel.request_focus = True
            display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(display_item, source_data_item=data_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        self.push_undo_command(command)

    def processing_duplicate(self):
        data_item = self.selected_data_item
        if data_item:
            self._perform_duplicate(data_item)

    class InsertDisplayItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", display_item: DisplayItem.DisplayItem, display_item_fn: typing.Callable[[], DisplayItem.DisplayItem]):
            super().__init__(_("Insert Display Item"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__display_item_proxy = None
            self.__display_item = display_item
            self.__display_item_fn = display_item_fn
            self.__display_item_index = None
            self.__undelete_log = None
            self.initialize()

        def close(self):
            self.__document_controller = None
            if self.__display_item_proxy:
                self.__display_item_proxy.close()
                self.__display_item_proxy = None
            self.__display_item_index = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            if self.__undelete_log:
                self.__undelete_log.close()
                self.__undelete_log = None
            super().close()

        def perform(self):
            document_controller = self.__document_controller
            display_item = self.__display_item
            request_focus = not display_item.is_live
            snapshot_display_item = self.__display_item_fn(display_item)
            if request_focus:
                # see https://github.com/nion-software/nionswift/issues/145
                document_controller.select_display_items_in_data_panel([snapshot_display_item])
                document_controller.notify_focused_display_changed(snapshot_display_item)
                inspector_panel = document_controller.find_dock_widget("inspector-panel").panel
                if inspector_panel is not None:
                    inspector_panel.request_focus = True
            document_controller.show_display_item(snapshot_display_item, source_display_item=snapshot_display_item, request_focus=request_focus)
            self.__display_item_proxy = display_item.create_proxy() if display_item else None

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self):
            self.__document_controller.document_model.undelete_all(self.__undelete_log)
            self.__undelete_log.close()
            self.__undelete_log = None
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self):
            display_item = self.__display_item_proxy.item if self.__display_item_proxy else None
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__display_item_index = self.__document_controller.document_model.display_items.index(display_item)
            self.__undelete_log = self.__document_controller.document_model.remove_display_item_with_log(display_item)
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

    def _perform_display_item_snapshot(self, display_item: DisplayItem.DisplayItem) -> None:
        command = DocumentController.InsertDisplayItemCommand(self, display_item, self.document_model.get_display_item_snapshot_new)
        command.perform()
        self.push_undo_command(command)

    def processing_snapshot(self):
        display_item = self.selected_display_item
        if display_item:
            self._perform_display_item_snapshot(display_item)

    def processing_display_copy(self):
        display_item = self.selected_display_item
        if display_item:
            command = DocumentController.InsertDisplayItemCommand(self, display_item, self.document_model.get_display_item_copy_new)
            command.perform()
            self.push_undo_command(command)

    class RemoveDisplayItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", display_item: DisplayItem.DisplayItem):
            super().__init__(_("Remove Display Item"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__display_item_index = document_controller.document_model.display_items.index(display_item)
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__display_item_index = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            document_model = self.__document_controller.document_model
            display_item = document_model.display_items[self.__display_item_index]
            self.__undelete_logs.append(document_model.remove_display_item_with_log(display_item))

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def processing_display_remove(self):
        display_item = self.selected_display_item
        if display_item:
            command = DocumentController.RemoveDisplayItemCommand(self, display_item)
            command.perform()
            self.push_undo_command(command)

    def processing_computation(self, expression, map: typing.Mapping[str, Symbolic.ComputationItem]=None):
        if map is None:
            map = dict()
            for variable_name, data_item in self.document_model.variable_to_data_item_map().items():
                map[variable_name] = Symbolic.make_item(data_item)
        data_item = DataItem.DataItem()
        data_item.ensure_data_source()
        data_item.title = _("Computation on ") + data_item.title
        computation = self.document_model.create_computation(expression)
        names = Symbolic.Computation.parse_names(expression)
        for variable_name, input_item in map.items():
            if variable_name in names:
                computation.create_input_item(variable_name, input_item)
        for item in computation.input_items:
            if isinstance(item, DataItem.DataItem) and item.category == "temporary":
                data_item.category = "temporary"
        self.document_model.append_data_item(data_item)
        self.document_model.set_data_item_computation(data_item, computation)
        display_item = self.document_model.get_display_item_for_data_item(data_item)
        self.show_display_item(display_item)
        return data_item

    def _get_two_data_sources(self):
        """Get two sensible data sources, which may be the same."""
        selected_display_items = self.selected_display_items
        if len(selected_display_items) < 2:
            selected_display_items = list()
            display_item = self.selected_display_item
            if display_item:
                selected_display_items.append(display_item)
        if len(selected_display_items) == 1:
            display_item = selected_display_items[0]
            data_item = display_item.data_item if display_item else None
            if display_item and len(display_item.graphic_selection.indexes) == 2:
                index1 = display_item.graphic_selection.anchor_index
                index2 = list(display_item.graphic_selection.indexes.difference({index1}))[0]
                graphic1 = display_item.graphics[index1]
                graphic2 = display_item.graphics[index2]
                if data_item:
                    if data_item.is_datum_1d and isinstance(graphic1, Graphics.IntervalGraphic) and isinstance(graphic2, Graphics.IntervalGraphic):
                        crop_graphic1 = graphic1
                        crop_graphic2 = graphic2
                    elif data_item.is_datum_2d and isinstance(graphic1, Graphics.RectangleTypeGraphic) and isinstance(graphic2, Graphics.RectangleTypeGraphic):
                        crop_graphic1 = graphic1
                        crop_graphic2 = graphic2
                    else:
                        crop_graphic1 = self.__get_crop_graphic(display_item)
                        crop_graphic2 = crop_graphic1
                else:
                    crop_graphic1 = self.__get_crop_graphic(display_item)
                    crop_graphic2 = crop_graphic1
            else:
                crop_graphic1 = self.__get_crop_graphic(display_item)
                crop_graphic2 = crop_graphic1
            return (display_item, crop_graphic1), (display_item, crop_graphic2)
        if len(selected_display_items) == 2:
            display_item1 = selected_display_items[0]
            crop_graphic1 = self.__get_crop_graphic(display_item1)
            display_item2 = selected_display_items[1]
            crop_graphic2 = self.__get_crop_graphic(display_item2)
            return (display_item1, crop_graphic1), (display_item2, crop_graphic2)
        return None

    def _perform_processing2(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_graphic1: typing.Optional[Graphics.Graphic], crop_graphic2: typing.Optional[Graphics.Graphic], fn) -> typing.Optional[DataItem.DataItem]:
        def process() -> DataItem.DataItem:
            new_data_item = fn(data_item1, data_item2, crop_graphic1, crop_graphic2)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
            return command.data_item
        else:
            command.close()
        return None

    def __processing_new2(self, fn):
        data_sources = self._get_two_data_sources()
        if data_sources:
            (display_item1, crop_graphic1), (display_item2, crop_graphic2) = data_sources
            return self._perform_processing2(display_item1, display_item2, crop_graphic1, crop_graphic2, fn)
        return None

    def processing_cross_correlate_new(self):
        return self.__processing_new2(self.document_model.get_cross_correlate_new)

    def _perform_processing(self, display_item: DisplayItem.DisplayItem, crop_graphic: typing.Optional[Graphics.Graphic], fn) -> typing.Optional[DataItem.DataItem]:
        def process() -> DataItem.DataItem:
            new_data_item = fn(display_item, crop_graphic)
            if new_data_item:
                new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
                self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
            return command.data_item
        else:
            command.close()
        return None

    def __processing_new(self, fn) -> typing.Optional[DataItem.DataItem]:
        display_item = self.selected_display_item
        crop_graphic = self.__get_crop_graphic(display_item)
        return self._perform_processing(display_item, crop_graphic, fn)

    def processing_fourier_filter_new(self):
        display_item = self.selected_display_item
        data_item = display_item.data_item if display_item else None
        if data_item:
            return self._perform_processing(display_item, None, self.document_model.get_fourier_filter_new)
        return None

    def processing_new(self, processing_id: str) -> typing.Optional[DataItem.DataItem]:
        display_item = self.selected_display_item
        data_item = display_item.data_item if display_item else None
        if data_item:
            return self._perform_processing(display_item, None, functools.partial(self.document_model.get_processing_new, processing_id))
        return None

    def __change_to_previous_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.change_to_previous_workspace()

    def __change_to_next_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.change_to_next_workspace()

    def __create_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.create_workspace()

    def __rename_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.rename_workspace()

    def __remove_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.remove_workspace()

    def __clone_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.clone_workspace()

    def toggle_filter(self):
        if self.workspace_controller.filter_row.visible:
            self.__last_display_filter = self.display_filter
            self.display_filter = ListModel.Filter(True)
        else:
            self.display_filter = self.__last_display_filter
        self.workspace_controller.filter_row.visible = not self.workspace_controller.filter_row.visible

    def prepare_data_item_script(self, *, do_log: bool=True) -> None:
        data_item = self.focused_data_item
        if data_item:
            data_item_var = self.document_model.assign_variable_to_data_item(data_item)
            if do_log: logging.debug("{} = Data Item with UUID {}".format(data_item_var, data_item.uuid))
            for console in self.__consoles:
                console.assign_data_item_var(data_item_var, data_item)

    def copy_uuid(self):
        display_item = self.selected_display_item
        data_item = display_item.data_item if display_item else None
        if display_item:
            current_index = display_item.graphic_selection.current_index
            if current_index is not None:
                graphic = display_item.graphics[current_index]
                uuid_str = str(graphic.uuid)
                self.ui.clipboard_set_text(uuid_str)
                return
        if data_item:
            uuid_str = str(data_item.uuid)
            self.ui.clipboard_set_text(uuid_str)
            return

    def _perform_create_empty_data_item(self) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = DataItem.DataItem()
            new_data_item.title = _("Untitled")
            self.document_model.append_data_item(new_data_item)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        self.push_undo_command(command)

    def create_empty_data_item(self):
        self._perform_create_empty_data_item()

    class InsertDataItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", data_items: typing.Sequence[DataItem.DataItem], index: int, display_panel: DisplayPanel.DisplayPanel=None, *, project: Project.Project = None):
            super().__init__(_("Insert Data Items"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__data_items = data_items  # only used in perform
            self.__data_item_index = index
            self.__data_item_indexes = list()
            self.__display_panel = display_panel  # only used in perform
            self.__project = project
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__data_items = None
            self.__data_item_index = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            document_model = self.__document_controller.document_model
            index = self.__data_item_index
            for data_item in self.__data_items:
                # insert will throw an exception if data item already exists in the project
                document_model.insert_data_item(index, data_item, auto_display=True, project=self.__project)
                self.__data_item_indexes.append(index)
                index += 1
            if self.__display_panel and self.__data_items:
                display_item = self.__document_controller.document_model.get_display_item_for_data_item(self.__data_items[-1])
                if display_item:
                    self.__display_panel.set_display_panel_display_item(display_item)
                    self.__display_panel.request_focus()

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self):
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            document_model = self.__document_controller.document_model
            data_items = [document_model.data_items[index] for index in self.__data_item_indexes]
            for data_item in data_items:
                if data_item in document_model.data_items:
                    self.__undelete_logs.append(document_model.remove_data_item_with_log(data_item, safe=True))
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

    def receive_project_files(self, file_paths: typing.Sequence[pathlib.Path], project: Project.Project, index: int = -1, threaded: bool = True) -> None:
        def receive_files_complete(received_data_items):
            def select_library_all():
                self.select_data_items_in_data_panel([received_data_items[0]])

            if len(received_data_items) > 0:
                self.queue_task(select_library_all)

        self.__receive_files(file_paths, index=index, threaded=threaded, completion_fn=receive_files_complete, project=project)

    # receive files into the document model. data_group and index can optionally
    # be specified. if data_group is specified, the item is added to an arbitrary
    # position in the document model (the end) and at the group at the position
    # specified by the index. if the data group is not specified, the item is added
    # at the index within the document model.
    def receive_files(self, files: typing.Sequence[str], data_group=None, index=-1, threaded=True, completion_fn=None,
                      display_panel: DisplayPanel.DisplayPanel = None, project: Project.Project = None) -> typing.Optional[
        typing.List[DataItem.DataItem]]:
        file_paths = [pathlib.Path(file_path) for file_path in files]
        return self.__receive_files(file_paths, data_group, index, threaded, completion_fn, display_panel, project=project)

    def __receive_files(self, file_paths: typing.Sequence[pathlib.Path],
                        data_group=None,
                        index=-1,
                        threaded=True,
                        completion_fn=None,
                        display_panel: DisplayPanel.DisplayPanel = None, *,
                        project: Project.Project = None) -> typing.Optional[typing.List[DataItem.DataItem]]:
        assert index is not None

        # this function will be called on a thread to receive files in the background.
        def receive_files_on_thread(file_paths: typing.Sequence[pathlib.Path], data_group: typing.Optional[DataGroup.DataGroup], index: int, completion_fn) -> typing.List[DataItem.DataItem]:

            received_data_items = list()

            with self.create_task_context_manager(_("Import Data Items"), "table", logging=threaded) as task:
                task.update_progress(_("Starting import."), (0, len(file_paths)))
                task_data = {"headers": ["Number", "File"]}

                for file_index, file_path in enumerate(file_paths):
                    data = task_data.setdefault("data", list())
                    file_name = file_path.name
                    task_data_entry = [str(file_index + 1), file_name]
                    data.append(task_data_entry)
                    task.update_progress(_("Importing item {}.").format(file_index + 1), (file_index + 1, len(file_paths)), task_data)
                    try:
                        data_items = ImportExportManager.ImportExportManager().read_data_items(self.ui, str(file_path))
                        if data_items:
                            received_data_items.extend(data_items)
                    except Exception as e:
                        logging.debug(f"Could not read image {file_path} / {e}")
                        traceback.print_exc()
                        traceback.print_stack()

                task.update_progress(_("Finishing importing."), (len(file_paths), len(file_paths)))

                if completion_fn:
                    completion_fn(received_data_items)

                return received_data_items

        def receive_files_complete(index, data_items):
            if data_group and isinstance(data_group, DataGroup.DataGroup):
                command = DocumentController.InsertDataGroupDataItemsCommand(self, data_group, data_items, index)
                command.perform()
                self.push_undo_command(command)
            else:
                index = index if index >= 0 else len(self.document_model.data_items)
                command = DocumentController.InsertDataItemsCommand(self, data_items, index, display_panel, project=project)
                command.perform()
                self.push_undo_command(command)
            if callable(completion_fn):
                completion_fn(data_items)

        if threaded:
            def threaded_receive_files_complete(index, data_items):
                self.queue_task(functools.partial(receive_files_complete, index, data_items))

            threading.Thread(target=receive_files_on_thread, args=(file_paths, data_group, index, functools.partial(threaded_receive_files_complete, index))).start()
            return None
        else:
            return receive_files_on_thread(file_paths, data_group, index, functools.partial(receive_files_complete, index))

    def create_context_menu_for_display(self, display_item: DisplayItem.DisplayItem, container=None, *, use_selection: bool=True):
        selected_display_items = self.selected_display_items if use_selection else [display_item]

        menu = self.create_context_menu()

        def show_in_new_window():
            self.new_window_with_data_item("data", display_item=display_item)

        if display_item is not None:
            menu.add_menu_item(_("Open in New Window"), show_in_new_window)

        data_item = display_item.data_item if display_item else None

        if display_item:

            def show():
                self.select_display_items_in_data_panel([display_item])

            menu.add_menu_item(_("Reveal"), show)

            # when exporting, queue the task so that the pop-up is allowed to close before the dialog appears.
            # without queueing, it originally led to a crash (tested in Qt 5.4.1 on Windows 7).

            def export_files():
                if display_item in selected_display_items:
                    self.export_files(selected_display_items)
                else:
                    self.export_file(display_item)

            menu.add_menu_item(_("Export..."), functools.partial(self.queue_task, export_files))  # queued to avoid pop-up menu issue

        if data_item and len(self.document_model.get_display_items_for_data_item(data_item)) == 1:

            def delete_data_item():
                # if the display item is not in the selected display items,
                # only delete that specific display item. otherwise, it is
                # part of the group, so delete all selected display items.
                if not display_item in selected_display_items:
                    self.delete_display_items([display_item], container)
                else:
                    self.delete_display_items(selected_display_items, container)

            menu.add_separator()
            menu.add_menu_item(_("Delete Data Item"), delete_data_item)

        elif display_item:

            def delete_display_item():
                # if the display item is not in the selected display items,
                # only delete that specific display item. otherwise, it is
                # part of the group, so delete all selected display items.
                if not display_item in selected_display_items:
                    self.delete_display_items([display_item], container)
                else:
                    self.delete_display_items(selected_display_items, container)

            menu.add_separator()
            menu.add_menu_item(_("Delete Display Item"), delete_display_item)

        if data_item:

            source_data_items = self.document_model.get_source_data_items(data_item)
            if len(source_data_items) > 0:
                menu.add_separator()
                for source_data_item in source_data_items:
                    def show_source_data_item(data_item):
                        self.select_data_item_in_data_panel(data_item)

                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Source "), source_data_item.title),
                                       functools.partial(show_source_data_item, source_data_item))

            dependent_data_items = self.document_model.get_dependent_data_items(data_item)
            if len(dependent_data_items) > 0:
                menu.add_separator()
                for dependent_data_item in dependent_data_items:
                    def show_dependent_data_item(data_item):
                        self.select_data_item_in_data_panel(data_item)

                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Dependent "), dependent_data_item.title),
                                       functools.partial(show_dependent_data_item, dependent_data_item))
        return menu
