# standard libraries
import copy
import functools
import gettext
import json
import logging
import math
import operator
import os.path
import pathlib
import sys
import threading
import time
import traceback
import typing
import uuid
import weakref

from nion.swift import ComputationPanel
from nion.swift import ConsoleDialog
from nion.swift import Decorators
from nion.swift import DisplayEditorPanel
from nion.swift import DisplayPanel
from nion.swift import ExportDialog
from nion.swift import FilterPanel
from nion.swift import RecorderPanel
from nion.swift import ScriptsDialog
from nion.swift import Task
from nion.swift import Undo
from nion.swift import Workspace
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import ImportExportManager
from nion.swift.model import Symbolic
from nion.ui import Dialog
from nion.ui import PreferencesDialog
from nion.ui import Window
from nion.ui import UserInterface
from nion.utils import Event
from nion.utils import ListModel
from nion.utils import Selection

_ = gettext.gettext


GRAPHICS_MIME_TYPE = "text/vnd.nion.graphics"

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
        if app:
            workspace_dir = app.workspace_dir
            workspace_name = os.path.splitext(os.path.split(workspace_dir)[1])[0] if workspace_dir else _("Workspace")
            self.title = "{0} Workspace - {1}".format(_("Nion Swift"), workspace_name)
        else:
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
        self.__data_items_model = ListModel.FilteredListModel(container=self.document_model, items_key="data_items")
        self.__data_items_model.filter_id = None  # extra tracking field
        self.__filtered_data_items_model = ListModel.FilteredListModel(items_key="data_items", container=self.__data_items_model)
        self.__filtered_displays_model = ListModel.FlattenedListModel(container=self.__filtered_data_items_model, master_items_key="data_items", child_items_key="displays", selection=self.selection)
        self.__last_display_filter = ListModel.Filter(True)
        self.filter_changed_event = Event.Event()

        self.__update_data_items_model(self.__data_items_model, None, None)

        def call_soon(fn):
            self.queue_task(fn)
            return True

        self.__call_soon_event_listener = self.document_model.call_soon_event.listen(call_soon)

        self.filter_controller = FilterPanel.FilterController(self)

        self.focused_library_item_changed_event = Event.Event()
        self.focused_data_item_changed_event = Event.Event()
        self.__focused_library_item = None
        self.__focused_data_item = None
        self.__focused_display = None
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
        self._library_menu = None
        self._processing_arithmetic_menu = None
        self._processing_reduce_menu = None
        self._processing_transform_menu = None
        self._processing_filter_menu = None
        self._processing_fourier_menu = None
        self._processing_graphics_menu = None
        self._processing_sequence_menu = None
        self._display_type_menu = None

        if self.__workspace_controller:
            self.__workspace_controller.close()
            self.__workspace_controller = None
        self.__call_soon_event_listener.close()
        self.__call_soon_event_listener = None
        self.__filtered_data_items_model.close()
        self.__filtered_data_items_model = None
        self.__filtered_displays_model.close()
        self.__filtered_displays_model = None
        self.filter_controller.close()
        self.filter_controller = None
        self.__data_items_model.close()
        self.__data_items_model = None
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

        self._library_menu = self.create_sub_menu()

        if self.app:
            recent_workspace_file_paths = self.app.get_recent_workspace_file_paths()
            for file_path in recent_workspace_file_paths[0:10]:
                root_path, file_name = os.path.split(file_path)
                name, ext = os.path.splitext(file_name)
                self._library_menu.add_menu_item(name, functools.partial(self.app.switch_library, file_path))
            if len(recent_workspace_file_paths) > 0:
                self._library_menu.add_separator()
            self._library_menu.add_menu_item(_("Choose..."), self.app.choose_library)
            self._library_menu.add_menu_item(_("Clear"), self.app.clear_libraries)

        self._new_window_action = self._file_menu.add_menu_item(_("New Window"), functools.partial(self.new_window_with_data_item, "library"), key_sequence="new")
        self._close_action = self._file_menu.add_menu_item(_("Close Window"), self.request_close, key_sequence="close")
        self._file_menu.add_separator()
        self._switch_library_action = self._file_menu.add_sub_menu(_("Switch Library"), self._library_menu)
        if self.app:
            self._open_library_action = self._file_menu.add_menu_item(_("Open Library..."), self.app.open_library, key_sequence="open")
            self._new_library_action = self._file_menu.add_menu_item(_("New Library..."), self.app.new_library, key_sequence="Ctrl+Shift+N")
        self._file_menu.add_separator()
        self._import_folder_action = self._file_menu.add_menu_item(_("Import Folder..."), self.__import_folder)
        self._import_action = self._file_menu.add_menu_item(_("Import Data..."), self.import_file)
        def export_files():
            selected_data_items = self.selected_data_items
            if len(selected_data_items) > 1:
                self.export_files(selected_data_items)
            elif len(selected_data_items) == 1:
                self.export_file(selected_data_items[0])
            elif self.selected_display_specifier.data_item:
                self.export_file(self.selected_display_specifier.data_item)
        self._export_action = self._file_menu.add_menu_item(_("Export..."), export_files)
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
        self._script_action = self._edit_menu.add_menu_item(_("Script"), self.prepare_data_item_script, key_sequence="Ctrl+Shift+K")
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

        self._processing_menu.add_menu_item(_("Snapshot"), self.processing_snapshot, key_sequence="Ctrl+S")
        self._processing_menu.add_menu_item(_("Duplicate"), self.processing_duplicate, key_sequence="Ctrl+D")
        self._processing_menu.add_separator()

        self._processing_menu.add_menu_item(_("Edit Data Item Scripts"), self.new_edit_computation_dialog, key_sequence="Ctrl+E")
        self._processing_menu.add_menu_item(_("Edit Display Script"), self.new_display_editor_dialog, key_sequence="Ctrl+Shift+D")
        self._processing_menu.add_separator()

        self._processing_fourier_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Fourier"), self._processing_fourier_menu)

        self._processing_fourier_menu.add_menu_item(_("FFT"), functools.partial(self.__processing_new, self.document_model.get_fft_new), key_sequence="Ctrl+F")
        self._processing_fourier_menu.add_menu_item(_("Inverse FFT"), functools.partial(self.__processing_new, self.document_model.get_ifft_new), key_sequence="Ctrl+Shift+F")
        self._processing_fourier_menu.add_menu_item(_("Auto Correlate"), functools.partial(self.__processing_new, self.document_model.get_auto_correlate_new))
        self._processing_fourier_menu.add_menu_item(_("Cross Correlate"), self.processing_cross_correlate_new)
        self._processing_fourier_menu.add_menu_item(_("Fourier Filter"), self.processing_fourier_filter_new)
        self._processing_fourier_menu.add_separator()
        self._processing_fourier_menu.add_menu_item(_("Add Spot Mask"), self.add_spot_graphic)
        self._processing_fourier_menu.add_menu_item(_("Add Angle Mask"), self.add_angle_graphic)
        self._processing_fourier_menu.add_menu_item(_("Add Band Pass Mask"), self.add_band_pass_graphic)

        self._processing_filter_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Filter"), self._processing_filter_menu)

        self._processing_filter_menu.add_menu_item(_("Sobel Filter"), functools.partial(self.__processing_new, self.document_model.get_sobel_new))
        self._processing_filter_menu.add_menu_item(_("Laplace Filter"), functools.partial(self.__processing_new, self.document_model.get_laplace_new))
        self._processing_filter_menu.add_menu_item(_("Gaussian Blur"), functools.partial(self.__processing_new, self.document_model.get_gaussian_blur_new))
        self._processing_filter_menu.add_menu_item(_("Median Filter"), functools.partial(self.__processing_new, self.document_model.get_median_filter_new))
        self._processing_filter_menu.add_menu_item(_("Uniform Filter"), functools.partial(self.__processing_new, self.document_model.get_uniform_filter_new))

        self._processing_transform_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Transform"), self._processing_transform_menu)

        self._processing_transform_menu.add_menu_item(_("Transpose and Flip"), functools.partial(self.__processing_new, self.document_model.get_transpose_flip_new))
        self._processing_transform_menu.add_menu_item(_("Resample"), functools.partial(self.__processing_new, self.document_model.get_resample_new))
        self._processing_transform_menu.add_menu_item(_("Crop"), functools.partial(self.__processing_new, self.document_model.get_crop_new))
        self._processing_transform_menu.add_menu_item(_("Resize"), functools.partial(self.__processing_new, self.document_model.get_resize_new))
        self._processing_transform_menu.add_menu_item(_("Convert to Scalar"), functools.partial(self.__processing_new, self.document_model.get_convert_to_scalar_new))

        self._processing_reduce_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Reduce"), self._processing_reduce_menu)

        self._processing_reduce_menu.add_menu_item(_("Slice Sum"), functools.partial(self.__processing_new, self.document_model.get_slice_sum_new))
        self._processing_reduce_menu.add_menu_item(_("Pick"), functools.partial(self.__processing_new, self.document_model.get_pick_new))
        self._processing_reduce_menu.add_menu_item(_("Pick Region (Sum)"), functools.partial(self.__processing_new, self.document_model.get_pick_region_new))
        self._processing_reduce_menu.add_menu_item(_("Pick Region (Average)"), functools.partial(self.__processing_new, self.document_model.get_pick_region_average_new))
        self._processing_reduce_menu.add_menu_item(_("Projection (Sum)"), functools.partial(self.__processing_new, self.document_model.get_projection_new))

        self._processing_arithmetic_menu = self.create_sub_menu()
        self._processing_menu.add_sub_menu(_("Arithmetic"), self._processing_arithmetic_menu)

        self._processing_arithmetic_menu.add_menu_item(_("Add"), functools.partial(self.__processing_new2, self.document_model.get_add_new))
        self._processing_arithmetic_menu.add_menu_item(_("Subtract"), functools.partial(self.__processing_new2, self.document_model.get_subtract_new))
        self._processing_arithmetic_menu.add_menu_item(_("Multiply"), functools.partial(self.__processing_new2, self.document_model.get_multiply_new))
        self._processing_arithmetic_menu.add_menu_item(_("Divide"), functools.partial(self.__processing_new2, self.document_model.get_divide_new))
        self._processing_arithmetic_menu.add_menu_item(_("Negate"), functools.partial(self.__processing_new, self.document_model.get_invert_new))
        self._processing_arithmetic_menu.add_separator()
        self._processing_arithmetic_menu.add_menu_item(_("Subtract Region Average"), functools.partial(self.__processing_new, self.document_model.get_subtract_region_average_new))

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
        self._view_menu.add_separator()
        self._view_menu.add_sub_menu(_("Display Panel Type"), self._display_type_menu)
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
                image = self.ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/logo3.png"))
                logo_button.icon = image
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
                column.add(make_label_row("Copyright 2012-2018 Nion Co. All Rights Reserved."))
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
    def data_items_model(self):
        return self.__data_items_model

    @property
    def filtered_displays_model(self):
        return self.__filtered_displays_model

    def __update_data_items_model(self, data_items_model: ListModel.FilteredListModel, data_group, filter_id):
        """Update the data item model with a new container, filter, and sorting.

        This is called when the data item model is created or when the user changes
        the data group or sorting settings.
        """

        with data_items_model.changes():  # change filter and sort together
            if data_group is not None:
                data_items_model.container = data_group
                data_items_model.filter = ListModel.Filter(True)
                data_items_model.sort_key = None
                data_items_model.filter_id = None
            elif filter_id == "latest-session":
                data_items_model.container = self.document_model
                data_items_model.filter = ListModel.EqFilter("session_id", self.document_model.session_id)
                data_items_model.sort_key = DataItem.sort_by_date_key
                data_items_model.sort_reverse = True
                data_items_model.filter_id = filter_id
            elif filter_id == "temporary":
                data_items_model.container = self.document_model
                data_items_model.filter = ListModel.NotEqFilter("category", "persistent")
                data_items_model.sort_key = DataItem.sort_by_date_key
                data_items_model.sort_reverse = True
                data_items_model.filter_id = filter_id
            elif filter_id == "none":  # not intended to be used directly
                data_items_model.container = self.document_model
                data_items_model.filter = ListModel.Filter(False)
                data_items_model.sort_key = DataItem.sort_by_date_key
                data_items_model.sort_reverse = True
                data_items_model.filter_id = filter_id
            else:  # "all"
                data_items_model.container = self.document_model
                data_items_model.filter = ListModel.EqFilter("category", "persistent")
                data_items_model.sort_key = DataItem.sort_by_date_key
                data_items_model.sort_reverse = True
                data_items_model.filter_id = None

    def create_data_items_model(self, data_group, filter_id) -> ListModel.FilteredListModel:
        data_items_model = ListModel.FilteredListModel(items_key="data_items")
        self.__update_data_items_model(data_items_model, data_group, filter_id)
        return data_items_model

    def set_data_group(self, data_group):
        if self.__data_items_model is not None:
            container = data_group if data_group else self.document_model
            if container != self.__data_items_model.container:
                self.__update_data_items_model(self.__data_items_model, data_group, self.__data_items_model.filter_id)
                self.filter_changed_event.fire(data_group, self.__data_items_model.filter_id)

    def set_filter(self, filter_id):
        if self.__data_items_model is not None:
            if filter_id != self.__data_items_model.filter_id:
                self.__update_data_items_model(self.__data_items_model, None, filter_id)
                self.filter_changed_event.fire(None, filter_id)

    def get_data_group_and_filter_id(self):
        # used for display panel initialization
        data_group = self.__data_items_model.container if self.__data_items_model.container != self.document_model else None
        filter_id = self.__data_items_model.filter_id
        return data_group, filter_id

    @property
    def display_filter(self) -> ListModel.Filter:
        return self.__filtered_data_items_model.filter

    @display_filter.setter
    def display_filter(self, display_filter: ListModel.Filter) -> None:
        if self.__filtered_data_items_model is not None:  # during close
            self.__filtered_data_items_model.filter = display_filter

    @property
    def selected_displays(self) -> typing.List[Display.Display]:
        selected_displays = list()
        displays = self.__filtered_displays_model.displays
        for index in self.selection.ordered_indexes:
            selected_displays.append(displays[index])
        return selected_displays

    @property
    def selected_data_items(self) -> typing.List[DataItem.DataItem]:
        selected_displays = self.selected_displays
        selected_data_items = list()
        for display in selected_displays:
            data_item = DataItem.DisplaySpecifier.from_display(display).data_item
            if data_item and not data_item in selected_data_items:
                selected_data_items.append(data_item)
        return selected_data_items

    @property
    def selected_library_items(self) -> typing.List[DataItem.LibraryItem]:
        selected_displays = self.selected_displays
        selected_library_items = list()
        for display in selected_displays:
            library_item = DataItem.DisplaySpecifier.from_display(display).library_item
            if library_item and not library_item in selected_library_items:
                selected_library_items.append(library_item)
        return selected_library_items

    def select_data_items_in_data_panel(self, data_items: typing.Sequence[DataItem.DataItem]) -> None:
        displays = self.filtered_displays_model.displays
        associated_displays = {data_item.primary_display_specifier.display for data_item in data_items}
        indexes = set()
        for index, display in enumerate(displays):
            if display in associated_displays:
                indexes.add(index)
        self.selection.set_multiple(indexes)
        if len(associated_displays) > 0:
            display = data_items[0].primary_display_specifier.display
            if display in displays:
                self.selection.anchor_index = displays.index(display)

    # track the selected data item. this can be called by ui elements when
    # they get focus. the selected data item will stay the same until another ui
    # element gets focus or the data item is removed from the document.
    def notify_focused_display_changed(self, display: typing.Optional[Display.Display]) -> None:
        if self.__focused_display != display:
            self.__focused_display = display
        display_specifier = DataItem.DisplaySpecifier.from_display(display)
        library_item = display_specifier.library_item
        if self.__focused_library_item != library_item:
            self.__focused_library_item = library_item
            self.focused_library_item_changed_event.fire(library_item)
        data_item = display_specifier.data_item
        if self.__focused_data_item != data_item:
            self.__focused_data_item = data_item
            self.focused_data_item_changed_event.fire(data_item)

    @property
    def focused_library_item(self) -> DataItem.LibraryItem:
        """Return the library item with keyboard focus."""
        return self.__focused_library_item

    @property
    def focused_data_item(self) -> DataItem.DataItem:
        """Return the data item with keyboard focus."""
        return self.__focused_data_item

    @property
    def focused_display(self) -> Display.Display:
        """Return the display with keyboard focus."""
        return self.__focused_display

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
    def selected_display_specifier(self):
        """Return the selected display specifier (data_item, display).

        The selected display is the display that has keyboard focus in the data panel or a display panel.
        """
        # first check for the [focused] data browser
        data_item = self.focused_data_item
        if data_item:
            return DataItem.DisplaySpecifier.from_data_item(data_item)
        # if not found, check for focused or selected image panel
        return DataItem.DisplaySpecifier.from_data_item(self.selected_display_panel.data_item if self.selected_display_panel else None)

    def delete_displays(self, displays: typing.Sequence[Display.Display]) -> None:
        library_items = list()
        container = self.__data_items_model.container
        if container is self.document_model:
            for display in displays:
                library_item = DataItem.DisplaySpecifier.from_display(display).library_item
                if library_item and library_item in self.document_model.data_items and library_item not in library_items:
                    library_items.append(library_item)
            if library_items:
                command = self.create_remove_library_items_command(library_items)
                command.perform()
                self.push_undo_command(command)
        elif isinstance(container, DataGroup.DataGroup):
            for display in displays:
                library_item = DataItem.DisplaySpecifier.from_display(display).library_item
                if library_item and library_item in container.data_items and library_item not in library_items:
                    library_items.append(library_item)
            if library_items:
                command = DocumentController.RemoveDataGroupLibraryItemsCommand(self.document_model, container, library_items)
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
            display = selected_display_panel.display if selected_display_panel else None
            self.notify_focused_display_changed(display)

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

    def new_window_with_data_item(self, workspace_id, data_item=None):
        # hack to work around Application <-> DocumentController interdependency.
        self.create_new_document_controller_event.fire(self.document_model, workspace_id, data_item)

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

    def export_file(self, data_item) -> None:
        # present a loadfile dialog to the user
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
            ImportExportManager.ImportExportManager().write_data_items_with_writer(self.ui, selected_writer, data_item, path)

    def export_files(self, data_items):
        if len(data_items) > 1:
            export_dialog = ExportDialog.ExportDialog(self.ui)
            export_dialog.on_accept = functools.partial(export_dialog.do_export, data_items)
            export_dialog.show()
            self.__dialogs.append(weakref.ref(export_dialog))
        elif len(data_items) == 1:
            self.export_file(data_items[0])

    # this method creates a task. it is thread safe.
    def create_task_context_manager(self, title, task_type, logging=True):
        task = Task.Task(title, task_type)  # NOTE: currently, tasks don't get deleted since they are displayed until exit.
        task_context_manager = Task.TaskContextManager(self, task, logging)
        self.task_created_event.fire(task)
        return task_context_manager

    def open_preferences(self):
        for dialog_weakref in self.__dialogs:
            if isinstance(dialog_weakref(), PreferencesDialog.PreferencesDialog):
                return

        preferences_dialog = PreferencesDialog.PreferencesDialog(self.ui, self.app)
        preferences_dialog.show()

        def close_preferences():
            self.__dialogs.remove(weakref.ref(preferences_dialog))

        preferences_dialog.on_close = close_preferences

        self.__dialogs.append(weakref.ref(preferences_dialog))

    def new_interactive_script_dialog(self):
        interactive_dialog = ScriptsDialog.RunScriptDialog(self)
        interactive_dialog.show()
        self.__dialogs.append(weakref.ref(interactive_dialog))

    def new_console_dialog(self):
        console_dialog = ConsoleDialog.ConsoleDialog(self)
        console_dialog.show()
        self.__dialogs.append(weakref.ref(console_dialog))

    def new_edit_computation_dialog(self, data_item=None):
        if not data_item:
            data_item = self.selected_display_specifier.data_item
        if data_item:
            interactive_dialog = ComputationPanel.EditComputationDialog(self, data_item)
            interactive_dialog.show()
            self.__dialogs.append(weakref.ref(interactive_dialog))

    def new_display_editor_dialog(self, data_item=None):
        if not data_item:
            data_item = self.selected_display_specifier.data_item
        if data_item:
            interactive_dialog = DisplayEditorPanel.DisplayEditorDialog(self, data_item)
            interactive_dialog.show()
            self.__dialogs.append(weakref.ref(interactive_dialog))

    def new_recorder_dialog(self, data_item=None):
        if not data_item:
            data_item = self.selected_display_specifier.data_item
        if data_item:
            interactive_dialog = RecorderPanel.RecorderDialog(self, data_item)
            interactive_dialog.show()
            self.__dialogs.append(weakref.ref(interactive_dialog))

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
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            mime_data = self.ui.clipboard_mime_data()
            if mime_data.has_format(GRAPHICS_MIME_TYPE):
                json_str = mime_data.data_as_string(GRAPHICS_MIME_TYPE)
                graphics_dict = json.loads(json_str)
                is_same_source = graphics_dict.get("src_uuid") == str(display_specifier.data_item.uuid)
                graphics = list()
                for graphic_dict in graphics_dict.get("graphics", list()):
                    graphic = Graphics.factory(lambda t: graphic_dict["type"])
                    graphic.read_from_mime_data(graphic_dict, is_same_source)
                    if graphic:
                        graphics.append(graphic)
                display.graphic_selection.clear()
                command = DisplayPanel.InsertGraphicsCommand(self, display, graphics)
                command.perform()
                self.push_undo_command(command)
                for graphic in graphics:
                    display.graphic_selection.add(display.graphics.index(graphic))
                return True
        return False

    def handle_delete(self):
        # delete key gets handled by key handlers, but this method gets called by menu items
        self.remove_selected_graphics()

    class InsertDataGroupLibraryItemCommand(Undo.UndoableCommand):
        def __init__(self, document_model, data_group: DataGroup.DataGroup, before_index: int, data_item: DataItem.DataItem):
            super().__init__("Insert Library Item")
            self.__document_model = document_model
            self.__data_group_uuid = data_group.uuid
            self.__before_index = before_index
            self.__data_item_uuid = data_item.uuid
            self.initialize()

        def close(self):
            self.__document_model = None
            self.__data_group_uuid = None
            self.__before_index = None
            self.__data_item_uuid = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            return data_group.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            data_group.modified_state = modified_state

        def perform(self) -> None:
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            data_item = self.__document_model.get_data_item_by_uuid(self.__data_item_uuid)
            data_group.insert_data_item(self.__before_index, data_item)

        def _undo(self) -> None:
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            data_group.remove_data_item(data_group.data_items[self.__before_index])

        def _redo(self) -> None:
            self.perform()

    def create_insert_data_group_library_item_command(self, data_group: DataGroup.DataGroup, before_index: int, data_item: DataItem) -> InsertDataGroupLibraryItemCommand:
        return DocumentController.InsertDataGroupLibraryItemCommand(self.document_model, data_group, before_index, data_item)

    class InsertDataGroupLibraryItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_controller: "DocumentController", data_group: DataGroup.DataGroup, library_items: typing.Sequence[DataItem.LibraryItem], index: int):
            super().__init__("Insert Library Items")
            self.__document_controller = document_controller
            self.__data_group_uuid = data_group.uuid
            self.__data_group_indexes = list()
            self.__data_group_uuids = list()
            self.__library_items = library_items  # only in perform
            self.__library_item_index = index
            self.__library_item_indexes = list()
            self.__undelete_logs = None
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__data_group_uuid = None
            self.__data_group_indexes = None
            self.__data_group_uuids = None
            self.__library_items = None
            self.__library_item_index = None
            self.__undelete_logs = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__document_controller.document_model.get_data_group_by_uuid(self.__data_group_uuid)
            return self.__document_controller.document_model.modified_state, data_group.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__document_controller.document_model.get_data_group_by_uuid(self.__data_group_uuid)
            self.__document_controller.document_model.modified_state, data_group.modified_state = modified_state

        def perform(self):
            document_model = self.__document_controller.document_model
            data_group = document_model.get_data_group_by_uuid(self.__data_group_uuid)
            index = self.__library_item_index
            for library_item in self.__library_items:
                if not document_model.get_data_item_by_uuid(library_item.uuid):
                    self.__library_item_indexes.append(len(document_model.data_items))
                    document_model.append_data_item(library_item)
            for library_item in self.__library_items:
                if not library_item in data_group.data_items:
                    data_group.insert_data_item(index, library_item)
                    self.__data_group_indexes.append(index)
                    self.__data_group_uuids.append(library_item.uuid)
                    index += 1
            self.__library_items = None

        def _undo(self) -> None:
            document_model = self.__document_controller.document_model
            data_group = self.__document_controller.document_model.get_data_group_by_uuid(self.__data_group_uuid)
            self.__undelete_logs = list()
            library_items = [data_group.data_items[index] for index in self.__data_group_indexes]
            for library_item in library_items:
                if library_item in data_group.data_items:
                    data_group.remove_data_item(library_item)
            library_items = [document_model.data_items[index] for index in self.__library_item_indexes]
            for library_item in library_items:
                if library_item in document_model.data_items:
                    self.__undelete_logs.append(document_model.remove_data_item(library_item, safe=True))

        def _redo(self) -> None:
            document_model = self.__document_controller.document_model
            data_group = self.__document_controller.document_model.get_data_group_by_uuid(self.__data_group_uuid)
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
            index = self.__library_item_index
            library_items = [document_model.get_data_item_by_uuid(library_item_uuid) for library_item_uuid in reversed(self.__data_group_uuids)]
            for library_item in library_items:
                if not library_item in data_group.data_items:
                    data_group.insert_data_item(index, library_item)

    class RemoveDataGroupLibraryItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_model, data_group: DataGroup.DataGroup, data_items: typing.Sequence[DataItem.DataItem]):
            super().__init__("Remove Library Item")
            self.__document_model = document_model
            self.__data_group_uuid = data_group.uuid
            combined = [(data_group.data_items.index(data_item), data_item.uuid) for data_item in data_items]
            combined = sorted(combined, key=operator.itemgetter(0), reverse=True)
            self.__data_item_indexes = list(map(operator.itemgetter(0), combined))
            self.__data_item_uuids = list(map(operator.itemgetter(1), combined))
            self.initialize()

        def _get_modified_state(self):
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            return data_group.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            data_group.modified_state = modified_state

        def perform(self) -> None:
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            data_items = [data_group.data_items[index] for index in self.__data_item_indexes]
            for data_item in data_items:
                if data_item in data_group.data_items:
                    data_group.remove_data_item(data_item)

        def _undo(self) -> None:
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            data_items = [self.__document_model.get_data_item_by_uuid(data_item_uuid) for data_item_uuid in self.__data_item_uuids]
            for index, data_item in zip(self.__data_item_indexes, data_items):
                data_group.insert_data_item(index, data_item)

        def _redo(self) -> None:
            self.perform()

    class RenameDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model, data_group: DataGroup.DataGroup, title: str):
            super().__init__("Rename Data Group")
            self.__document_model = document_model
            self.__data_group_uuid = data_group.uuid
            self.__title = title
            self.__new_title = None
            self.initialize()

        def _get_modified_state(self):
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            return data_group.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            data_group.modified_state = modified_state

        def perform(self) -> None:
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            self.__new_title = data_group.title
            data_group.title = self.__title

        def _undo(self) -> None:
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            data_group.title = self.__new_title

        def _redo(self) -> None:
            self.perform()

    def create_rename_data_group_command(self, data_group: DataGroup.DataGroup, title: str) -> RenameDataGroupCommand:
        return DocumentController.RenameDataGroupCommand(self.document_model, data_group, title)

    class InsertDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model, container: typing.Union[DataGroup.DataGroup, DocumentModel.DocumentModel], before_index: int, data_group: DataGroup.DataGroup):
            super().__init__("Insert Data Group")
            self.__document_model = document_model
            self.__container_uuid = container.uuid
            self.__before_index = before_index
            self.__data_group_properties = data_group.write_to_dict()
            self.__data_group_uuid = data_group.uuid
            self.initialize()

        def _get_modified_state(self):
            container = self.__document_model.get_data_group_or_document_model_by_uuid(self.__container_uuid)
            return container.modified_state

        def _set_modified_state(self, modified_state) -> None:
            container = self.__document_model.get_data_group_or_document_model_by_uuid(self.__container_uuid)
            container.modified_state = modified_state

        def perform(self) -> None:
            container = self.__document_model.get_data_group_or_document_model_by_uuid(self.__container_uuid)
            data_group = DataGroup.DataGroup()
            data_group.read_from_dict(self.__data_group_properties)
            container.insert_data_group(self.__before_index, data_group)

        def _undo(self) -> None:
            container = self.__document_model.get_data_group_or_document_model_by_uuid(self.__container_uuid)
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            container.remove_data_group(data_group)

        def _redo(self) -> None:
            self.perform()

    def create_insert_data_group_command(self, container: typing.Union[DataGroup.DataGroup, DocumentModel.DocumentModel], before_index: int, data_group: DataGroup.DataGroup) -> InsertDataGroupCommand:
        return DocumentController.InsertDataGroupCommand(self.document_model, container, before_index, data_group)

    class RemoveDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model, container: typing.Union[DataGroup.DataGroup, DocumentModel.DocumentModel], data_group: DataGroup.DataGroup):
            super().__init__("Remove Data Group")
            self.__document_model = document_model
            self.__container_uuid = container.uuid
            self.__data_group_uuid = data_group.uuid
            self.__data_group_properties = None
            self.__data_group_index = None
            self.initialize()

        def _get_modified_state(self):
            container = self.__document_model.get_data_group_or_document_model_by_uuid(self.__container_uuid)
            return container.modified_state

        def _set_modified_state(self, modified_state) -> None:
            container = self.__document_model.get_data_group_or_document_model_by_uuid(self.__container_uuid)
            container.modified_state = modified_state

        def perform(self) -> None:
            container = self.__document_model.get_data_group_or_document_model_by_uuid(self.__container_uuid)
            data_group = self.__document_model.get_data_group_by_uuid(self.__data_group_uuid)
            self.__data_group_properties = data_group.write_to_dict()
            self.__data_group_index = container.data_groups.index(data_group)
            container.remove_data_group(data_group)

        def _undo(self) -> None:
            container = self.__document_model.get_data_group_or_document_model_by_uuid(self.__container_uuid)
            data_group = DataGroup.DataGroup()
            data_group.read_from_dict(self.__data_group_properties)
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
        data_group_empty = len(data_group.data_items) == 0 and len(data_group.data_groups) == 0
        if data_group_empty:
            assert data_group in container.data_groups
            command = DocumentController.RemoveDataGroupCommand(self.document_model, container, data_group)
            command.perform()
            self.push_undo_command(command)

    def add_line_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            graphic = Graphics.LineGraphic()
            graphic.start = (0.2, 0.2)
            graphic.end = (0.8, 0.8)
            command = DisplayPanel.InsertGraphicsCommand(self, display, [graphic])
            command.perform()
            self.push_undo_command(command)
            display.graphic_selection.set(display.graphics.index(graphic))
            return graphic
        return None

    def add_rectangle_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            command = DisplayPanel.InsertGraphicsCommand(self, display, [graphic])
            command.perform()
            self.push_undo_command(command)
            display.graphic_selection.set(display.graphics.index(graphic))
            return graphic
        return None

    def add_ellipse_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            graphic = Graphics.EllipseGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            command = DisplayPanel.InsertGraphicsCommand(self, display, [graphic])
            command.perform()
            self.push_undo_command(command)
            display.graphic_selection.set(display.graphics.index(graphic))
            return graphic
        return None

    def add_point_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            graphic = Graphics.PointGraphic()
            graphic.position = (0.5,0.5)
            command = DisplayPanel.InsertGraphicsCommand(self, display, [graphic])
            command.perform()
            self.push_undo_command(command)
            display.graphic_selection.set(display.graphics.index(graphic))
            return graphic
        return None

    def add_interval_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            graphic = Graphics.IntervalGraphic()
            graphic.start = 0.25
            graphic.end = 0.75
            command = DisplayPanel.InsertGraphicsCommand(self, display, [graphic])
            command.perform()
            self.push_undo_command(command)
            display.graphic_selection.set(display.graphics.index(graphic))
            return graphic
        return None

    def add_channel_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            graphic = Graphics.ChannelGraphic()
            graphic.position = 0.5
            command = DisplayPanel.InsertGraphicsCommand(self, display, [graphic])
            command.perform()
            self.push_undo_command(command)
            display.graphic_selection.set(display.graphics.index(graphic))
            return graphic
        return None

    def add_spot_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            graphic = Graphics.SpotGraphic()
            graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
            command = DisplayPanel.InsertGraphicsCommand(self, display, [graphic])
            command.perform()
            self.push_undo_command(command)
            display.graphic_selection.set(display.graphics.index(graphic))
            return graphic
        return None

    def add_angle_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            graphic = Graphics.WedgeGraphic()
            graphic.start_angle = 0
            graphic.end_angle = (3/4) * math.pi
            command = DisplayPanel.InsertGraphicsCommand(self, display, [graphic])
            command.perform()
            self.push_undo_command(command)
            display.graphic_selection.set(display.graphics.index(graphic))
            return graphic
        return None

    def add_band_pass_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            graphic = Graphics.RingGraphic()
            graphic.radius_1 = 0.15
            graphic.radius_2 = 0.25
            command = DisplayPanel.InsertGraphicsCommand(self, display, [graphic])
            command.perform()
            self.push_undo_command(command)
            display.graphic_selection.set(display.graphics.index(graphic))
            return graphic
        return None

    def copy_selected_graphics(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            if display.graphic_selection.has_selection:
                graphic_dict_list = list()
                graphics = [display.graphics[index] for index in display.graphic_selection.indexes]
                for graphic in graphics:
                    graphic_dict_list.append(graphic.mime_data_dict())
                graphics_dict = {"src_uuid": str(display_specifier.data_item.uuid), "graphics": graphic_dict_list}
                json_str = json.dumps(graphics_dict)
                graphic_mime_data = self.ui.create_mime_data()
                graphic_mime_data.set_data_as_string(GRAPHICS_MIME_TYPE, json_str)
                self.ui.clipboard_set_mime_data(graphic_mime_data)
                return True
        return False

    def remove_selected_graphics(self) -> None:
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            if display.graphic_selection.has_selection:
                graphics = [display.graphics[index] for index in display.graphic_selection.indexes]
                if graphics:
                    command = self.create_remove_graphics_command(display, graphics)
                    command.perform()
                    self.push_undo_command(command)

    class RemoveGraphicsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", display: Display.Display, graphics: typing.Sequence[Graphics.Graphic]):
            super().__init__(_("Remove Graphics"))
            self.__document_controller = document_controller
            self.__display_uuid = display.uuid
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__graphic_indexes = [display.graphics.index(graphic) for graphic in graphics]
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__display_uuid = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__graphic_indexes = None
            super().close()

        def perform(self):
            display = self.__document_controller.document_model.get_display_by_uuid(self.__display_uuid)
            self.__undelete_logs = list()
            graphics = [display.graphics[index] for index in self.__graphic_indexes]
            for graphic in graphics:
                self.__undelete_logs.append(display.remove_graphic(graphic, safe=True))

        def _get_modified_state(self):
            display = self.__document_controller.document_model.get_display_by_uuid(self.__display_uuid)
            return display.modified_state, self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state):
            display = self.__document_controller.document_model.get_display_by_uuid(self.__display_uuid)
            display.modified_state, self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def create_remove_graphics_command(self, display, graphics):
        return DocumentController.RemoveGraphicsCommand(self, display, graphics)

    class RemoveLibraryItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", library_items: typing.Sequence[DataItem.LibraryItem]):
            super().__init__(_("Remove Library Items"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__library_item_indexes = [document_controller.document_model.data_items.index(library_item) for library_item in library_items]
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__library_item_indexes = None
            super().close()

        def perform(self):
            self.__undelete_logs = list()
            document_model = self.__document_controller.document_model
            library_items = [document_model.data_items[index] for index in self.__library_item_indexes]
            for library_item in library_items:
                if library_item in document_model.data_items:
                    self.__undelete_logs.append(document_model.remove_data_item(library_item, safe=True))

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state):
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def create_remove_library_items_command(self, library_items: typing.Sequence[DataItem.LibraryItem]) -> Undo.UndoableCommand:
        return DocumentController.RemoveLibraryItemsCommand(self, library_items)

    def add_data_element(self, data_element, source_data_item=None):
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        if data_item:
            self.document_model.append_data_item(data_item)
        return data_item

    def add_data(self, data, title=None):
        data_element = { "data": data, "title": title }
        return self.add_data_element(data_element)

    def display_data_item(self, display_specifier, source_data_item=None):
        library_item = display_specifier.library_item
        assert library_item is not None
        result_display_panel = self.next_result_display_panel()
        if result_display_panel:
            result_display_panel.set_display_panel_data_item(library_item)
            result_display_panel.request_focus()
        self.select_data_item_in_data_panel(library_item)
        self.notify_focused_display_changed(display_specifier.display)
        inspector_panel = self.find_dock_widget("inspector-panel").panel
        if inspector_panel is not None:
            inspector_panel.request_focus = True

    def __get_crop_graphic(self, display_specifier):
        crop_graphic = None
        data_item = display_specifier.data_item
        display = display_specifier.display
        current_index = display.graphic_selection.current_index if display else None
        graphic = display.graphics[current_index] if current_index is not None else None
        if data_item and graphic:
            if data_item.is_datum_1d and isinstance(graphic, Graphics.IntervalGraphic):
                crop_graphic = graphic
            elif data_item.is_datum_2d and isinstance(graphic, Graphics.RectangleTypeGraphic):
                crop_graphic = graphic
        return crop_graphic

    def __get_mask_graphics(self, display_specifier):
        mask_graphics = list()
        data_item = display_specifier.data_item
        if data_item and len(data_item.dimensional_shape) == 2:
            display = display_specifier.display
            current_index = display.graphic_selection.current_index
            if current_index is not None:
                graphic = display.graphics[current_index]
                if hasattr(graphic, 'get_mask'):
                    mask_graphics.append(graphic)
        return mask_graphics

    def processing_fft(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_fft_new))

    def processing_ifft(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_ifft_new))

    def processing_gaussian_blur(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_gaussian_blur_new))

    def processing_resample(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_resample_new))

    def processing_crop(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_crop_new))

    def processing_slice(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_slice_sum_new))

    def processing_projection(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_projection_new))

    def processing_line_profile(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_line_profile_new))

    def processing_invert(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_invert_new))

    class InsertLibraryItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", library_item_fn: typing.Callable[[], DataItem.LibraryItem]):
            super().__init__(_("Insert Library Item"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__library_item_uuid = None
            self.__library_item_fn = library_item_fn
            self.__library_item_index = None
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__library_item_uuid = None
            self.__library_item_fn = None
            self.__library_item_index = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            super().close()

        def perform(self):
            self.__library_item_uuid = self.__library_item_fn().uuid

        @property
        def library_item(self):
            return self.__document_controller.document_model.get_data_item_by_uuid(self.__library_item_uuid)

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self):
            self.__document_controller.document_model.undelete_all(self.__undelete_log)
            self.__library_item_uuid = self.__document_controller.document_model.data_items[self.__library_item_index].uuid
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self):
            library_item = self.__document_controller.document_model.get_data_item_by_uuid(self.__library_item_uuid)
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__library_item_index = self.__document_controller.document_model.data_items.index(library_item)
            self.__undelete_log = self.__document_controller.document_model.remove_data_item(library_item, safe=True)
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

    def create_insert_library_item_command(self, library_item_fn: typing.Callable[[], DataItem.LibraryItem]) -> Undo.UndoableCommand:
        return DocumentController.InsertLibraryItemCommand(self, library_item_fn)

    def _perform_duplicate(self, library_item: DataItem.LibraryItem) -> None:
        def process() -> DataItem.LibraryItem:
            new_data_item = self.document_model.copy_data_item(library_item)
            new_data_item.title = _("Clone of ") + library_item.title
            new_data_item.category = library_item.category
            self.select_data_item_in_data_panel(new_data_item)
            self.notify_focused_display_changed(new_data_item.primary_display_specifier.display)
            inspector_panel = self.find_dock_widget("inspector-panel").panel
            if inspector_panel is not None:
                inspector_panel.request_focus = True
            display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item)
            self.display_data_item(display_specifier, source_data_item=library_item)
            return new_data_item
        command = self.create_insert_library_item_command(process)
        command.perform()
        self.push_undo_command(command)

    def processing_duplicate(self):
        data_item = self.selected_display_specifier.data_item
        if data_item:
            self._perform_duplicate(data_item)

    def _perform_snapshot(self, library_item: DataItem.LibraryItem) -> None:
        def process() -> DataItem.LibraryItem:
            data_item_copy = self.document_model.get_snapshot_new(library_item)
            self.select_data_item_in_data_panel(data_item_copy)
            self.notify_focused_display_changed(data_item_copy.primary_display_specifier.display)
            inspector_panel = self.find_dock_widget("inspector-panel").panel
            if inspector_panel is not None:
                inspector_panel.request_focus = True
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_copy)
            self.display_data_item(display_specifier, source_data_item=library_item)
            return data_item_copy
        command = self.create_insert_library_item_command(process)
        command.perform()
        self.push_undo_command(command)

    def processing_snapshot(self):
        data_item = self.selected_display_specifier.data_item
        if data_item:
            self._perform_snapshot(data_item)

    def fix_display_limits(self, display_specifier):
        display = display_specifier.display
        if display:
            display.display_limits = display.get_calculated_display_values(True).data_range

    def processing_computation(self, expression, map=None):
        if map is None:
            map = dict()
            for variable_name, data_item in self.document_model.variable_to_data_item_map().items():
                map[variable_name] = self.document_model.get_object_specifier(data_item)
        data_item = DataItem.DataItem()
        data_item.ensure_data_source()
        data_item.title = _("Computation on ") + data_item.title
        computation = self.document_model.create_computation(expression)
        names = Symbolic.Computation.parse_names(expression)
        for variable_name, object_specifier in map.items():
            if variable_name in names:
                computation.create_object(variable_name, object_specifier)
        for variable in computation.variables:
            specifier = variable.specifier
            if specifier:
                object = self.document_model.resolve_object_specifier(variable.specifier)
                if isinstance(object, DataItem.DataItem) and object.category == "temporary":
                    data_item.category = "temporary"
        self.document_model.append_data_item(data_item)
        self.document_model.set_data_item_computation(data_item, computation)
        self.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item))
        return data_item

    def _get_two_data_sources(self):
        """Get two sensible data sources, which may be the same."""
        selected_data_items = self.selected_data_items
        if len(selected_data_items) < 2:
            selected_data_items = list()
            data_item = self.selected_display_specifier.data_item
            if data_item:
                selected_data_items.append(data_item)
        if len(selected_data_items) == 1:
            display_specifier = DataItem.DisplaySpecifier.from_data_item(selected_data_items[0])
            data_item = display_specifier.data_item
            display = display_specifier.display
            if display and len(display.graphic_selection.indexes) == 2:
                index1 = display.graphic_selection.anchor_index
                index2 = list(display.graphic_selection.indexes.difference({index1}))[0]
                graphic1 = display.graphics[index1]
                graphic2 = display.graphics[index2]
                if data_item:
                    if data_item.is_datum_1d and isinstance(graphic1, Graphics.IntervalGraphic) and isinstance(graphic2, Graphics.IntervalGraphic):
                        crop_graphic1 = graphic1
                        crop_graphic2 = graphic2
                    elif data_item.is_datum_2d and isinstance(graphic1, Graphics.RectangleTypeGraphic) and isinstance(graphic2, Graphics.RectangleTypeGraphic):
                        crop_graphic1 = graphic1
                        crop_graphic2 = graphic2
                    else:
                        crop_graphic1 = self.__get_crop_graphic(display_specifier)
                        crop_graphic2 = crop_graphic1
                else:
                    crop_graphic1 = self.__get_crop_graphic(display_specifier)
                    crop_graphic2 = crop_graphic1
            else:
                crop_graphic1 = self.__get_crop_graphic(display_specifier)
                crop_graphic2 = crop_graphic1
            return (data_item, crop_graphic1), (data_item, crop_graphic2)
        if len(selected_data_items) == 2:
            display_specifier1 = DataItem.DisplaySpecifier.from_data_item(selected_data_items[0])
            data_item1 = display_specifier1.data_item
            crop_graphic1 = self.__get_crop_graphic(display_specifier1)
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(selected_data_items[1])
            data_item2 = display_specifier2.data_item
            crop_graphic2 = self.__get_crop_graphic(display_specifier2)
            return (data_item1, crop_graphic1), (data_item2, crop_graphic2)
        return None

    def _perform_processing2(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_graphic1: typing.Optional[Graphics.Graphic], crop_graphic2: typing.Optional[Graphics.Graphic], fn) -> typing.Optional[DataItem.DataItem]:
        def process() -> DataItem.LibraryItem:
            new_data_item = fn(data_item1, data_item2, crop_graphic1, crop_graphic2)
            new_display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item)
            self.display_data_item(new_display_specifier)
            return new_data_item
        command = self.create_insert_library_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertLibraryItemCommand)
        if command.library_item:
            self.push_undo_command(command)
            return command.library_item
        else:
            command.close()
        return None

    def __processing_new2(self, fn):
        data_sources = self._get_two_data_sources()
        if data_sources:
            (data_item1, crop_graphic1), (data_item2, crop_graphic2) = data_sources
            return self._perform_processing2(data_item1, data_item2, crop_graphic1, crop_graphic2, fn)
        return None

    def processing_cross_correlate_new(self):
        return self.__processing_new2(self.document_model.get_cross_correlate_new)

    def _perform_processing(self, data_item: DataItem.DataItem, crop_graphic: typing.Optional[Graphics.Graphic], fn) -> typing.Optional[DataItem.DataItem]:
        def process() -> DataItem.LibraryItem:
            new_data_item = fn(data_item, crop_graphic)
            new_display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item)
            self.display_data_item(new_display_specifier)
            return new_data_item
        command = self.create_insert_library_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertLibraryItemCommand)
        if command.library_item:
            self.push_undo_command(command)
            return command.library_item
        else:
            command.close()
        return None

    def __processing_new(self, fn) -> typing.Optional[DataItem.DataItem]:
        display_specifier = self.selected_display_specifier
        data_item = display_specifier.data_item
        crop_graphic = self.__get_crop_graphic(display_specifier)
        if data_item:
            return self._perform_processing(data_item, crop_graphic, fn)
        return None

    def processing_fourier_filter_new(self):
        display_specifier = self.selected_display_specifier
        data_item = display_specifier.data_item
        if data_item:
            return self._perform_processing(data_item, None, self.document_model.get_fourier_filter_new)
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

    def toggle_filter(self):
        if self.workspace_controller.filter_row.visible:
            self.__last_display_filter = self.display_filter
            self.display_filter = ListModel.Filter(True)
        else:
            self.display_filter = self.__last_display_filter
        self.workspace_controller.filter_row.visible = not self.workspace_controller.filter_row.visible

    def prepare_data_item_script(self, *, do_log: bool=True) -> None:
        library_item = self.focused_library_item
        if library_item:
            library_item_var = self.document_model.assign_variable_to_library_item(library_item)
            if do_log: logging.debug("{} = Library Item with UUID {}".format(library_item_var, library_item.uuid))
            for console in self.__consoles:
                console.assign_library_item_var(library_item_var, library_item)

    def copy_uuid(self):
        display_specifier = self.selected_display_specifier
        display = display_specifier.display
        data_item = display_specifier.data_item
        if display:
            current_index = display.graphic_selection.current_index
            if current_index is not None:
                graphic = display.graphics[current_index]
                uuid_str = str(graphic.uuid)
                self.ui.clipboard_set_text(uuid_str)
                return
        if data_item:
            uuid_str = str(data_item.uuid)
            self.ui.clipboard_set_text(uuid_str)
            return

    def _perform_create_empty_data_item(self) -> None:
        def process() -> DataItem.LibraryItem:
            new_data_item = DataItem.DataItem()
            new_data_item.title = _("Untitled")
            self.document_model.append_data_item(new_data_item)
            new_display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item)
            self.display_data_item(new_display_specifier)
            return new_data_item
        command = self.create_insert_library_item_command(process)
        command.perform()
        self.push_undo_command(command)

    def create_empty_data_item(self):
        self._perform_create_empty_data_item()

    class InsertLibraryItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", library_items: typing.Sequence[DataItem.LibraryItem], index: int, display_panel: DisplayPanel.DisplayPanel=None):
            super().__init__(_("Insert Library Items"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__library_items = library_items  # only used in perform
            self.__library_item_index = index
            self.__library_item_indexes = list()
            self.__display_panel = display_panel  # only used in perform
            self.__undelete_logs = None
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__library_items = None
            self.__library_item_index = None
            self.__undelete_logs = None
            super().close()

        def perform(self):
            document_model = self.__document_controller.document_model
            index = self.__library_item_index
            for library_item in self.__library_items:
                if not document_model.get_data_item_by_uuid(library_item.uuid):
                    document_model.insert_data_item(index, library_item)
                    self.__library_item_indexes.append(index)
                    index += 1
            if self.__display_panel and self.__library_items:
                self.__display_panel.set_display_panel_data_item(self.__library_items[-1])
                self.__display_panel.request_focus()

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self):
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__undelete_logs = list()
            document_model = self.__document_controller.document_model
            library_items = [document_model.data_items[index] for index in self.__library_item_indexes]
            for library_item in library_items:
                if library_item in document_model.data_items:
                    self.__undelete_logs.append(document_model.remove_data_item(library_item, safe=True))
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

    # receive files into the document model. data_group and index can optionally
    # be specified. if data_group is specified, the item is added to an arbitrary
    # position in the document model (the end) and at the group at the position
    # specified by the index. if the data group is not specified, the item is added
    # at the index within the document model.
    def receive_files(self, file_paths, data_group=None, index=-1, threaded=True, completion_fn=None, display_panel: DisplayPanel.DisplayPanel=None):
        assert index is not None

        # this function will be called on a thread to receive files in the background.
        def receive_files_on_thread(file_paths, data_group, index, completion_fn):

            received_data_items = list()

            with self.create_task_context_manager(_("Import Data Items"), "table", logging=threaded) as task:
                task.update_progress(_("Starting import."), (0, len(file_paths)))
                task_data = {"headers": ["Number", "File"]}

                for file_index, file_path in enumerate(file_paths):
                    data = task_data.setdefault("data", list())
                    root_path, file_name = os.path.split(file_path)
                    task_data_entry = [str(file_index + 1), file_name]
                    data.append(task_data_entry)
                    task.update_progress(_("Importing item {}.").format(file_index + 1), (file_index + 1, len(file_paths)), task_data)
                    try:
                        data_items = ImportExportManager.ImportExportManager().read_data_items(self.ui, file_path)
                        if data_items:
                            received_data_items.extend(data_items)
                    except Exception as e:
                        logging.debug("Could not read image %s / %s", file_path, str(e))
                        traceback.print_exc()
                        traceback.print_stack()

                task.update_progress(_("Finishing importing."), (len(file_paths), len(file_paths)))

                if completion_fn:
                    completion_fn(received_data_items)

                return received_data_items

        def receive_files_complete(index, data_items):
            if data_group and isinstance(data_group, DataGroup.DataGroup):
                command = DocumentController.InsertDataGroupLibraryItemsCommand(self, data_group, data_items, index)
                command.perform()
                self.push_undo_command(command)
            else:
                index = index if index >= 0 else len(self.document_model.data_items)
                command = DocumentController.InsertLibraryItemsCommand(self, data_items, index, display_panel)
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

    def create_context_menu_for_display(self, display: Display.Display, container=None):
        menu = self.create_context_menu()
        library_item = DataItem.DisplaySpecifier.from_display(display).library_item
        if library_item:
            data_item = DataItem.DisplaySpecifier.from_display(display).data_item

            if not container:
                container = self.data_items_model.container
                container = DataGroup.get_data_item_container(container, library_item)

            def delete():
                selected_library_items = self.selected_library_items
                if not library_item in selected_library_items:
                    if isinstance(container, DocumentModel.DocumentModel):
                        command = self.create_remove_library_items_command([library_item])
                        command.perform()
                        self.push_undo_command(command)
                    elif isinstance(container, DataGroup.DataGroup):
                        command = DocumentController.RemoveDataGroupLibraryItemsCommand(self.document_model, container, [library_item])
                        command.perform()
                        self.push_undo_command(command)
                else:
                    command = self.create_remove_library_items_command(selected_library_items)
                    command.perform()
                    self.push_undo_command(command)

            if data_item is not None:

                def show_in_new_window():
                    self.new_window_with_data_item("data", data_item=data_item)

                menu.add_menu_item(_("Open in New Window"), show_in_new_window)

            def show():
                self.select_data_item_in_data_panel(library_item)
            menu.add_menu_item(_("Reveal"), show)

            menu.add_menu_item(_("Delete Library Item"), delete)

            # when exporting, queue the task so that the pop-up is allowed to close before the dialog appears.
            # without queueing, it originally led to a crash (tested in Qt 5.4.1 on Windows 7).
            if data_item is not None:

                def export_files():
                    selected_data_items = self.selected_data_items
                    if data_item in selected_data_items:
                        self.export_files(selected_data_items)
                    else:
                        self.export_file(data_item)

                menu.add_menu_item(_("Export..."), functools.partial(self.queue_task, export_files))  # queued to avoid pop-up menu issue

            source_data_items = self.document_model.get_source_data_items(library_item)
            if len(source_data_items) > 0:
                menu.add_separator()
                for source_data_item in source_data_items:
                    def show_source_data_item(data_item):
                        self.select_data_item_in_data_panel(data_item)

                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Source "), source_data_item.title),
                                       functools.partial(show_source_data_item, source_data_item))

            dependent_data_items = self.document_model.get_dependent_data_items(library_item)
            if len(dependent_data_items) > 0:
                menu.add_separator()
                for dependent_data_item in dependent_data_items:
                    def show_dependent_data_item(data_item):
                        self.select_data_item_in_data_panel(data_item)

                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Dependent "), dependent_data_item.title),
                                       functools.partial(show_dependent_data_item, dependent_data_item))
        return menu
