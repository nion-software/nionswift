# standard libraries
import asyncio
import concurrent.futures
import copy
import datetime
import gettext
import json
import logging
import os
import shutil
import sys
import typing

# third party libraries
# None

# local libraries
from nion.swift import DataPanel
from nion.swift import DocumentController
from nion.swift import FilterPanel
from nion.swift import HistogramPanel
from nion.swift import InfoPanel
from nion.swift import Inspector
from nion.swift import MetadataPanel
from nion.swift import Panel
from nion.swift import SessionPanel
from nion.swift import Task
from nion.swift import Test
from nion.swift import ToolbarPanel
from nion.swift import Workspace
from nion.swift.model import Cache
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import HardwareSource
from nion.swift.model import PlugInManager
from nion.swift.model import Utility
from nion.ui import Application as UIApplication
from nion.ui import Dialog
from nion.ui import Widgets
from nion.utils import Selection

_ = gettext.gettext

app = None


# facilitate bootstrapping the application
class Application(UIApplication.Application):

    def __init__(self, ui, set_global=True, resources_path=None):
        super().__init__(ui)

        global app

        ui.set_application_info("Nion Swift", "Nion", "nion.com")

        self.ui.persistence_root = "3"  # sets of preferences
        self.__resources_path = resources_path
        self.version_str = "0.13.0"
        self.workspace_dir = None

        self.__event_loop = None

        if True or set_global:
            app = self  # hack to get the single instance set. hmm. better way?

        self.__document_model = None

        # a list of document controllers in the application.
        self.__document_controllers = []
        self.__menu_handlers = []

        # map these document controller events to listener tokens.
        # when the document controller closes, remove its listeners and
        # then remove it from the list of document controllers.
        # when the document controller requests a new document controller,
        # respond in this class by creating a new document controller.
        self.__did_close_event_listeners = dict()
        self.__create_new_event_listeners = dict()

        workspace_manager = Workspace.WorkspaceManager()
        workspace_manager.register_panel(SessionPanel.SessionPanel, "session-panel", _("Session"), ["left", "right"], "right", {"min-width": 320, "height": 80})
        workspace_manager.register_panel(DataPanel.DataPanel, "data-panel", _("Data Panel"), ["left", "right"], "left", {"min-width": 320, "height": 400})
        workspace_manager.register_panel(HistogramPanel.HistogramPanel, "histogram-panel", _("Histogram"), ["left", "right"], "right", {"min-width": 320, "height": 140})
        workspace_manager.register_panel(InfoPanel.InfoPanel, "info-panel", _("Info"), ["left", "right"], "right", {"min-width": 320, "height": 60})
        workspace_manager.register_panel(Inspector.InspectorPanel, "inspector-panel", _("Inspector"), ["left", "right"], "right", {"min-width": 320})
        workspace_manager.register_panel(Task.TaskPanel, "task-panel", _("Task Panel"), ["left", "right"], "right", {"min-width": 320})
        workspace_manager.register_panel(Panel.OutputPanel, "output-panel", _("Output"), ["bottom"], "bottom", {"min-width": 480, "min-height": 200})
        workspace_manager.register_panel(ToolbarPanel.ToolbarPanel, "toolbar-panel", _("Toolbar"), ["top"], "top", {"height": 30})
        workspace_manager.register_panel(MetadataPanel.MetadataPanel, "metadata-panel", _("Metadata"), ["left", "right"], "right", {"width": 320, "height": 8})
        workspace_manager.register_filter_panel(FilterPanel.FilterPanel)

    def initialize(self, *, load_plug_ins=True, use_root_dir=True):
        # configure the event loop object
        logger = logging.getLogger()
        old_level = logger.level
        logger.setLevel(logging.INFO)
        self.__event_loop = asyncio.new_event_loop()  # outputs a debugger message!
        logger.setLevel(old_level)
        # load plug-ins
        if load_plug_ins:
            PlugInManager.load_plug_ins(self, get_root_dir() if use_root_dir else None)

    def deinitialize(self):
        # shut down hardware source manager, unload plug-ins, and really exit ui
        HardwareSource.HardwareSourceManager().close()
        PlugInManager.unload_plug_ins()
        with open(os.path.join(self.ui.get_data_location(), "PythonConfig.ini"), 'w') as f:
            f.write(sys.prefix + '\n')
        # give cancelled tasks a chance to finish
        self.__event_loop.stop()
        self.__event_loop.run_forever()
        try:
            # this assumes that all outstanding tasks finish in a reasonable time (i.e. no infinite loops).
            self.__event_loop.run_until_complete(asyncio.gather(*asyncio.Task.all_tasks(loop=self.__event_loop), loop=self.__event_loop))
        except concurrent.futures.CancelledError:
            pass
        # now close
        # due to a bug in Python libraries, the default executor needs to be shutdown explicitly before the event loop
        # see http://bugs.python.org/issue28464
        if self.__event_loop._default_executor:
            self.__event_loop._default_executor.shutdown()
        self.__event_loop.close()
        self.__event_loop = None
        self.ui.close()

    def run(self):
        """Alternate start which allows ui to control event loop."""
        self.ui.run(self)

    def exit(self):
        # close all document windows
        for document_controller in copy.copy(self.__document_controllers):
            # closing the document window will trigger the about_to_close event to be called which
            # will then call document controller close which will fire its did_close_event which will
            # remove the document controller from the list of document controllers.
            document_controller.request_close()
        # document model is reference counted; when the no document controller holds a reference to the
        # document model, it will be closed.

    def periodic(self) -> None:
        if self.__event_loop:  # special for shutdown
            self.__event_loop.stop()
            self.__event_loop.run_forever()

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        return self.__event_loop

    @property
    def document_model(self):
        return self.__document_model

    # for testing
    def _set_document_model(self, document_model):
        self.__document_model = document_model

    def __migrate_library(self, workspace_dir: str, welcome_message_enabled: bool=True) -> str:
        """ Migrate library to latest version. """
        library_path_11 = os.path.join(workspace_dir, "Nion Swift Workspace.nslib")
        library_path_12 = os.path.join(workspace_dir, "Nion Swift Library 12.nslib")
        if not os.path.exists(library_path_12):
            if os.path.exists(library_path_11):
                if welcome_message_enabled:
                    logging.info("Migrating from library 11 to 12: %s -> %s", library_path_11, library_path_12)
                shutil.copyfile(library_path_11, library_path_12)
        return library_path_12

    def start(self, skip_choose=False, fixed_workspace_dir=None):
        """
            Start the application.

            Looks for workspace_location persistent string. If it doesn't find it, uses a default
            workspace location.

            Then checks to see if that workspace exists. If not and if skip_choose has not been
            set to True, asks the user for a workspace location. User may choose new folder or
            existing location. This works by putting up the dialog which will either call start
            again or exit.

            Creates workspace in location if it doesn't exist.

            Migrates database to latest version.

            Creates document model, resources path, etc.
        """
        if fixed_workspace_dir:
            workspace_dir = fixed_workspace_dir
        else:
            documents_dir = self.ui.get_document_location()
            workspace_dir = os.path.join(documents_dir, "Nion Swift Libraries")
            workspace_dir = self.ui.get_persistent_string("workspace_location", workspace_dir)
        cache_filename = "Nion Swift Cache {version}.nscache".format(version=DataItem.DataItem.writer_version)
        welcome_message_enabled = fixed_workspace_dir is None
        library_path = self.__migrate_library(workspace_dir, welcome_message_enabled)
        cache_path = os.path.join(workspace_dir, cache_filename)
        if not skip_choose and not os.path.exists(library_path):
            self.choose_library()
            return True
        self.workspace_dir = workspace_dir
        create_new_document = not os.path.exists(library_path)
        if create_new_document:
            if welcome_message_enabled:
                logging.info("Creating new document: %s", library_path)
        else:
            if welcome_message_enabled:
                logging.info("Using existing document %s", library_path)
        library_storage = DocumentModel.FilePersistentStorage(library_path)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([os.path.join(workspace_dir, "Nion Swift Data {version}".format(version=DataItem.DataItem.writer_version))])
        counts = DocumentModel.read_data_items_version_stats(file_persistent_storage_system)
        if counts[2] > 0:

            assert fixed_workspace_dir is None

            def do_ignore():
                self.continue_start(cache_path, create_new_document, file_persistent_storage_system, library_storage, workspace_dir, True)
                return True

            def do_upgrade():
                self.continue_start(cache_path, create_new_document, file_persistent_storage_system, library_storage, workspace_dir, False)
                return True

            class UpgradeDialog(Dialog.ActionDialog):
                def __init__(self, ui):
                    super().__init__(ui)

                    self.add_button(_("Upgrade"), do_upgrade)

                    self.add_button(_("Ignore"), do_ignore)

                    column = self.ui.create_column_widget()
                    column.add_spacing(12)

                    row_one = self.ui.create_row_widget()
                    row_one.add_spacing(13)
                    row_one.add(self.ui.create_label_widget("{0} data items need to be updated.".format(counts[2])))
                    row_one.add_stretch()
                    row_one.add_spacing(13)
                    column.add(row_one)
                    column.add_spacing(4)

                    row_two = self.ui.create_row_widget()
                    row_two.add_spacing(13)
                    row_two.add(self.ui.create_label_widget("{0} data items are newer than this version and won't be loaded.".format(counts[1])))
                    row_two.add_stretch()
                    row_two.add_spacing(13)
                    column.add(row_two)
                    column.add_spacing(4)

                    row_three = self.ui.create_row_widget()
                    row_three.add_spacing(13)
                    row_three.add(self.ui.create_label_widget("{0} data items match this version.".format(counts[0])))
                    row_three.add_stretch()
                    row_three.add_spacing(13)
                    column.add(row_three)
                    column.add_spacing(4)

                    row_three = self.ui.create_row_widget()
                    row_three.add_spacing(13)
                    row_three.add(self.ui.create_label_widget("If you choose to upgrade, the upgraded items will not\nbe able to be loaded in earlier versions.".format(counts[0])))
                    row_three.add_stretch()
                    row_three.add_spacing(13)
                    column.add_spacing(8)
                    column.add(row_three)
                    column.add_spacing(4)

                    column.add_spacing(12)
                    column.add_stretch()

                    self.content.add(column)

            upgrade_dialog = UpgradeDialog(self.ui)
            upgrade_dialog.show()

        else:
            self.continue_start(cache_path, create_new_document, file_persistent_storage_system, library_storage, workspace_dir, True, welcome_message=welcome_message_enabled)

        return True

    def continue_start(self, cache_path, create_new_document, file_persistent_storage_system, library_storage, workspace_dir, ignore_older_files, welcome_message=True):
        storage_cache = Cache.DbStorageCache(cache_path)
        DocumentModel.DocumentModel.computation_min_period = 0.1
        auto_migrations = list()
        auto_migrations.append(DocumentModel.AutoMigration([os.path.join(workspace_dir, "Nion Swift Data")]))
        auto_migrations.append(DocumentModel.AutoMigration([os.path.join(workspace_dir, "Nion Swift Data 10")]))
        auto_migrations.append(DocumentModel.AutoMigration([os.path.join(workspace_dir, "Nion Swift Data 11")]))
        document_model = DocumentModel.DocumentModel(library_storage=library_storage,
                                                     persistent_storage_system=file_persistent_storage_system,
                                                     storage_cache=storage_cache, ignore_older_files=ignore_older_files,
                                                     auto_migrations=auto_migrations)
        document_model.create_default_data_groups()
        document_model.start_dispatcher()
        # parse the hardware aliases file
        alias_path = os.path.join(self.workspace_dir, "aliases.ini")
        HardwareSource.parse_hardware_aliases_config_file(alias_path)
        # create the document controller
        document_controller = self.create_document_controller(document_model, "library")
        if self.__resources_path is not None:
            document_model.create_sample_images(self.__resources_path)
        workspace_history = self.ui.get_persistent_object("workspace_history", list())
        if workspace_dir in workspace_history:
            workspace_history.remove(workspace_dir)
        workspace_history.insert(0, workspace_dir)
        self.ui.set_persistent_object("workspace_history", workspace_history)
        self.ui.set_persistent_string("workspace_location", workspace_dir)
        if welcome_message:
            logging.info("Welcome to Nion Swift.")
        if create_new_document and len(document_model.data_items) > 0:
            document_controller.selected_display_panel.set_display_panel_data_item(document_model.data_items[0])
            document_controller.selected_display_panel.perform_action("set_fill_mode")

    def stop(self):
        # program is really stopping, clean up.
        self.deinitialize()

    def get_recent_workspace_file_paths(self):
        workspace_history = self.ui.get_persistent_object("workspace_history", list())
        # workspace_history = ["/Users/cmeyer/Movies/Crap/Test1", "/Users/cmeyer/Movies/Crap/Test7_new"]
        return [file_path for file_path in workspace_history if file_path != self.workspace_dir and os.path.exists(file_path)]

    def switch_library(self, recent_workspace_file_path, skip_choose=False, fixed_workspace_dir=None):
        self.exit()
        self.ui.set_persistent_string("workspace_location", recent_workspace_file_path)
        self.start(skip_choose=skip_choose, fixed_workspace_dir=fixed_workspace_dir)

    def clear_libraries(self):
        self.ui.remove_persistent_key("workspace_history")

    def pose_open_library_dialog(self) -> typing.Optional[str]:
        documents_dir = self.ui.get_document_location()
        workspace_dir, directory = self.ui.get_existing_directory_dialog(_("Choose Library Folder"), documents_dir)
        if workspace_dir:
            path = os.path.join(workspace_dir, "Nion Swift Workspace.nslib")
            if not os.path.exists(path):
                with open(path, "w") as fp:
                    json.dump({}, fp)
            return workspace_dir
        return None

    def open_library(self):
        workspace_dir = self.pose_open_library_dialog()
        if workspace_dir:
            app.switch_library(workspace_dir)

    def new_library(self):

        class NewLibraryDialog(Dialog.ActionDialog):

            def __init__(self, ui, app):
                super().__init__(ui, title=_("New Library"), app=app, persistent_id="new_library_dialog")

                self.directory = self.ui.get_persistent_string("library_directory", self.ui.get_document_location())

                library_base_name = _("Nion Swift Library") + " " + datetime.datetime.now().strftime("%Y%m%d")
                library_base_index = 0
                library_base_index_str = ""
                while os.path.exists(os.path.join(self.directory, library_base_name + library_base_index_str)):
                    library_base_index += 1
                    library_base_index_str = " " + str(library_base_index)

                self.library_name = library_base_name + library_base_index_str

                def handle_new():
                    self.library_name = self.__library_name_field.text
                    workspace_dir = os.path.join(self.directory, self.library_name)
                    Cache.db_make_directory_if_needed(workspace_dir)
                    path = os.path.join(workspace_dir, "Nion Swift Workspace.nslib")
                    if not os.path.exists(path):
                        with open(path, "w") as fp:
                            json.dump({}, fp)
                    if os.path.exists(path):
                        app.switch_library(workspace_dir)
                        return True
                    return False

                def handle_new_and_close():
                    handle_new()
                    self.request_close()
                    return False

                column = self.ui.create_column_widget()

                directory_header_row = self.ui.create_row_widget()
                directory_header_row.add_spacing(13)
                directory_header_row.add(self.ui.create_label_widget(_("Libraries Folder: "), properties={"font": "bold"}))
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

                library_name_header_row = self.ui.create_row_widget()
                library_name_header_row.add_spacing(13)
                library_name_header_row.add(self.ui.create_label_widget(_("Library Name: "), properties={"font": "bold"}))
                library_name_header_row.add_stretch()
                library_name_header_row.add_spacing(13)

                library_name_row = self.ui.create_row_widget()
                library_name_row.add_spacing(26)
                library_name_field = self.ui.create_line_edit_widget(properties={"width": 400})
                library_name_field.text = self.library_name
                library_name_field.on_return_pressed = handle_new_and_close
                library_name_field.on_escape_pressed = self.request_close
                library_name_row.add(library_name_field)
                library_name_row.add_stretch()
                library_name_row.add_spacing(13)

                column.add_spacing(12)
                column.add(directory_header_row)
                column.add_spacing(8)
                column.add(show_directory_row)
                column.add_spacing(8)
                column.add(choose_directory_row)
                column.add_spacing(16)
                column.add(library_name_header_row)
                column.add_spacing(8)
                column.add(library_name_row)
                column.add_stretch()
                column.add_spacing(16)

                def choose() -> None:
                    existing_directory, directory = self.ui.get_existing_directory_dialog(_("Choose Library Directory"), self.directory)
                    if existing_directory:
                        self.directory = existing_directory
                        directory_label.text = self.directory
                        self.ui.set_persistent_string("library_directory", self.directory)

                choose_directory_button.on_clicked = choose

                self.add_button(_("Cancel"), lambda: True)
                self.add_button(_("Create Library"), handle_new)

                self.content.add(column)

                self.__library_name_field = library_name_field

            def show(self):
                super().show()
                self.__library_name_field.focused = True

        new_library_dialog = NewLibraryDialog(self.ui, self)
        new_library_dialog.show()

    def choose_library(self):

        pose_open_library_dialog_fn = self.pose_open_library_dialog

        workspace_history = self.ui.get_persistent_object("workspace_history", list())
        nslib_paths = [os.path.join(file_path, "Nion Swift Workspace.nslib") for file_path in workspace_history]
        items = [(path, datetime.datetime.fromtimestamp(os.path.getmtime(path))) for path in nslib_paths if os.path.exists(path)]

        class ChooseLibraryDialog(Dialog.ActionDialog):

            def __init__(self, ui, app):
                super().__init__(ui, _("Choose Library"))

                current_item_ref = [None]

                def handle_choose():
                    current_item = current_item_ref[0]
                    if current_item:
                        app.switch_library(current_item)
                        return True
                    return False

                def handle_new():
                    workspace_dir = pose_open_library_dialog_fn()
                    if workspace_dir:
                        items.insert(0, (workspace_dir, datetime.datetime.now()))
                        list_widget.items = items
                        list_widget.set_selected_index(0)
                        app.switch_library(workspace_dir)
                        return True
                    return False

                self.add_button(_("New..."), handle_new)
                self.add_button(_("Other..."), handle_new)
                self.add_button(_("Cancel"), lambda: True)
                self.add_button(_("Choose"), handle_choose)

                path_label = ui.create_label_widget()

                prompt_row = ui.create_row_widget()
                prompt_row.add_spacing(13)
                prompt_row.add(ui.create_label_widget(_("Which library do you want Nion Swift to use?"), properties={"stylesheet": "font-weight: bold"}))
                prompt_row.add_spacing(13)
                prompt_row.add_stretch()

                explanation1_row = ui.create_row_widget()
                explanation1_row.add_spacing(13)
                explanation1_row.add(ui.create_label_widget(_("You can select a library from the list, find another library, or create a new library.")))
                explanation1_row.add_spacing(13)
                explanation1_row.add_stretch()

                explanation2_row = ui.create_row_widget()
                explanation2_row.add_spacing(13)
                explanation2_row.add(ui.create_label_widget(_("The same library will be used the next time you open Nion Swift.")))
                explanation2_row.add_spacing(13)
                explanation2_row.add_stretch()

                def selection_changed(indexes):
                    if len(indexes) == 1:
                        item = items[list(indexes)[0]]
                        current_item_ref[0] = os.path.dirname(item[0])
                        path_label.text = os.path.dirname(item[0])
                    else:
                        current_item_ref[0] = None
                        path_label.text = None

                def stringify_item(item):
                    date_utc = item[1]
                    tz_minutes = Utility.local_utcoffset_minutes(date_utc)
                    date_local = date_utc + datetime.timedelta(minutes=tz_minutes)
                    return str(os.path.basename(os.path.dirname(item[0]))) + " (" + date_local.strftime("%c") + ")"

                def item_selected(index):
                    item = items[index]
                    current_item_ref[0] = os.path.dirname(item[0])
                    path_label.text = os.path.dirname(item[0])
                    handle_choose()
                    self.request_close()

                list_widget = Widgets.StringListWidget(ui, items, Selection.Style.single_or_none, stringify_item, properties={"min-height": 200, "min-width": 560})
                list_widget.on_selection_changed = selection_changed
                list_widget.on_item_selected = item_selected
                list_widget.on_cancel = self.request_close
                if len(items) > 0:
                    list_widget.set_selected_index(0)

                items_row = ui.create_row_widget()
                items_row.add_spacing(13)
                items_row.add(list_widget)
                items_row.add_spacing(13)
                items_row.add_stretch()

                path_row = ui.create_row_widget()
                path_row.add_spacing(13)
                path_row.add(path_label)
                path_row.add_spacing(13)
                path_row.add_stretch()

                column = ui.create_column_widget()
                column.add_spacing(18)
                column.add(prompt_row)
                column.add_spacing(6)
                column.add(explanation1_row)
                column.add(explanation2_row)
                column.add_spacing(12)
                column.add(items_row)
                column.add_spacing(6)
                column.add(path_row)
                column.add_spacing(6)
                column.add_stretch()
                self.content.add(column)

                self.__list_widget = list_widget

            def show(self):
                super().show()
                self.__list_widget.focused = True

        if len(items) == 0:
            # for initial startup (or with no preferences) try to use a default location
            # to avoid the user having to go through the horrendous choose dialog immediately.
            try:
                documents_dir = self.ui.get_document_location()
                workspace_dir = os.path.join(documents_dir, "Nion Swift Library")
                Cache.db_make_directory_if_needed(workspace_dir)
                path = os.path.join(workspace_dir, "Nion Swift Workspace.nslib")
                if not os.path.exists(path):
                    with open(path, "w") as fp:
                        json.dump({}, fp)
                if os.path.exists(path):
                    app.switch_library(workspace_dir)
                    return
            except Exception as e:
                pass

        choose_library_dialog = ChooseLibraryDialog(self.ui, self)
        choose_library_dialog.show()

    def create_document_controller(self, document_model, workspace_id, data_item=None):
        self._set_document_model(document_model)  # required to allow API to find document model
        document_controller = DocumentController.DocumentController(self.ui, document_model, workspace_id=workspace_id, app=self)
        self.__did_close_event_listeners[document_controller] = document_controller.did_close_event.listen(self.__document_controller_did_close)
        self.__create_new_event_listeners[document_controller] = document_controller.create_new_document_controller_event.listen(self.create_document_controller)
        self.__register_document_controller(document_controller)
        # attempt to set data item / group
        if data_item:
            display_panel = document_controller.selected_display_panel
            if display_panel:
                display_panel.set_display_panel_data_item(data_item)
        document_controller.show()
        return document_controller

    def __document_controller_did_close(self, document_controller):
        self.__did_close_event_listeners[document_controller].close()
        del self.__did_close_event_listeners[document_controller]
        self.__create_new_event_listeners[document_controller].close()
        del self.__create_new_event_listeners[document_controller]
        self.__document_controllers.remove(document_controller)

    def __register_document_controller(self, document_controller: DocumentController.DocumentController) -> None:
        assert document_controller not in self.__document_controllers
        self.__document_controllers.append(document_controller)
        # when a document window is registered, tell the menu handlers
        for menu_handler in self.__menu_handlers:  # use 'handler' to avoid name collision
            menu_handler(document_controller)

    @property
    def document_controllers(self) -> typing.List[DocumentController.DocumentController]:
        return copy.copy(self.__document_controllers)

    def register_menu_handler(self, new_menu_handler):
        assert new_menu_handler not in self.__menu_handlers
        self.__menu_handlers.append(new_menu_handler)
        # when a menu handler is registered, let it immediately know about existing menu handlers
        for document_controller in self.__document_controllers:
            new_menu_handler(document_controller)
        # return the menu handler so that it can be used to unregister (think: lambda)
        return new_menu_handler

    def unregister_menu_handler(self, menu_handler):
        self.__menu_handlers.remove(menu_handler)

    @property
    def menu_handlers(self) -> typing.List:
        return copy.copy(self.__menu_handlers)

    def run_all_tests(self):
        Test.run_all_tests()


def get_root_dir():
    root_dir = os.path.dirname((os.path.dirname(os.path.abspath(__file__))))
    path_ascend_count = 2
    for i in range(path_ascend_count):
        root_dir = os.path.dirname(root_dir)
    return root_dir
