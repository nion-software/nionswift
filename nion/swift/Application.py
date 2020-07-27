# standard libraries
import asyncio
import copy
import datetime
import functools
import gettext
import json
import logging
import operator
import os
import pathlib
import sys
import typing
import uuid

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
from nion.swift import ProjectPanel
from nion.swift import SessionPanel
from nion.swift import Task
from nion.swift import Test
from nion.swift import ToolbarPanel
from nion.swift import Workspace
from nion.swift.model import ApplicationData
from nion.swift.model import Cache
from nion.swift.model import ColorMaps
from nion.swift.model import DocumentModel
from nion.swift.model import FileStorageSystem
from nion.swift.model import HardwareSource
from nion.swift.model import PlugInManager
from nion.swift.model import Profile
from nion.ui import Application as UIApplication
from nion.ui import Dialog
from nion.ui import UserInterface
from nion.ui import Window as UIWindow
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import Registry

_ = gettext.gettext

app = None


# facilitate bootstrapping the application
class Application(UIApplication.BaseApplication):
    count = 0  # useful for detecting leaks in tests

    def __init__(self, ui, set_global=True, resources_path=None):
        super().__init__(ui)
        self.__class__.count += 1

        # reset these values for tests. otherwise tests run slower after app.start is called in any previous test.
        DocumentModel.DocumentModel.computation_min_period = 0.0
        DocumentModel.DocumentModel.computation_min_factor = 0.0

        logging.getLogger("migration").setLevel(logging.ERROR)
        logging.getLogger("loader").setLevel(logging.ERROR)

        global app

        ui.set_application_info("Nion Swift", "Nion", "nion.com")

        self.ui.persistence_root = "3"  # sets of preferences
        self.__resources_path = resources_path
        self.version_str = "0.14.8"

        self.document_model_available_event = Event.Event()

        if True or set_global:
            app = self  # hack to get the single instance set. hmm. better way?

        self.__profile = None
        self.__document_model = None

        self.__menu_handlers = []

        Registry.register_component(Inspector.DeclarativeImageChooserConstructor(self), {"declarative_constructor"})

        workspace_manager = Workspace.WorkspaceManager()
        workspace_manager.register_panel(SessionPanel.SessionPanel, "session-panel", _("Session"), ["left", "right"], "right", {"min-width": 320, "height": 80})
        workspace_manager.register_panel(ProjectPanel.CollectionsPanel, "collections-panel", _("Collections"), ["left", "right"], "left", {"min-width": 320, "min-height": 200})
        workspace_manager.register_panel(DataPanel.DataPanel, "data-panel", _("Data Panel"), ["left", "right"], "left", {"min-width": 320, "min-height": 320})
        workspace_manager.register_panel(HistogramPanel.HistogramPanel, "histogram-panel", _("Histogram"), ["left", "right"], "right", {"min-width": 320, "height": 140})
        workspace_manager.register_panel(InfoPanel.InfoPanel, "info-panel", _("Info"), ["left", "right"], "right", {"min-width": 320, "height": 60})
        workspace_manager.register_panel(Inspector.InspectorPanel, "inspector-panel", _("Inspector"), ["left", "right"], "right", {"min-width": 320})
        workspace_manager.register_panel(Task.TaskPanel, "task-panel", _("Task Panel"), ["left", "right"], "right", {"min-width": 320})
        workspace_manager.register_panel(Panel.OutputPanel, "output-panel", _("Output"), ["bottom"], "bottom", {"min-width": 480, "min-height": 200})
        workspace_manager.register_panel(ToolbarPanel.ToolbarPanel, "toolbar-panel", _("Toolbar"), ["top"], "top", {"height": 30})
        workspace_manager.register_panel(MetadataPanel.MetadataPanel, "metadata-panel", _("Metadata"), ["left", "right"], "right", {"width": 320, "height": 8})
        workspace_manager.register_filter_panel(FilterPanel.FilterPanel)

    def initialize(self, *, load_plug_ins=True, use_root_dir=True):
        super().initialize()
        # configure app data
        if load_plug_ins:
            logging.info("Launch time " + str(datetime.datetime.now()))
            logging.info("Python version " + str(sys.version.replace('\n', '')))
            logging.info("User interface class " + type(self.ui).__name__ + " / " + type(self.ui.proxy).__name__)
            logging.info("Qt version " + self.ui.get_qt_version())
            app_data_file_path = self.ui.get_configuration_location() / pathlib.Path("nionswift_appdata.json")
            ApplicationData.set_file_path(app_data_file_path)
            logging.info("Application data: " + str(app_data_file_path))
            PlugInManager.load_plug_ins(self, get_root_dir() if use_root_dir else None)
            color_maps_dir = self.ui.get_configuration_location() / pathlib.Path("Color Maps")
            if color_maps_dir.exists():
                logging.info("Loading color maps from " + str(color_maps_dir))
                ColorMaps.load_color_maps(color_maps_dir)
            else:
                logging.info("NOT Loading color maps from " + str(color_maps_dir) + " (missing)")

    def deinitialize(self):
        # shut down hardware source manager, unload plug-ins, and really exit ui
        HardwareSource.HardwareSourceManager().close()
        PlugInManager.unload_plug_ins()
        self.__class__.count -= 1
        super().deinitialize()

    def run(self):
        """Alternate start which allows ui to control event loop."""
        self.ui.run(self)

    @property
    def profile(self) -> typing.Optional[Profile.Profile]:
        return self.__profile

    @property
    def document_model(self):
        return self.__document_model

    # for testing
    def _set_document_model(self, document_model):
        self.__document_model = document_model

    def start(self, *, profile_dir: pathlib.Path = None, profile: Profile.Profile = None) -> bool:
        """Start the application.

        Creates the profile object using profile_path parameter (for testing), the profile path constructed from the
        name stored in preferences, or a default profile path.

        Attaches recent projects if profile is freshly created. The recent projects will initially be disabled and
        will require the user to explicitly upgrade them.

        Creates the document model with the profile.

        Creates the document window (aka document controller) with the document model.
        """
        logging.getLogger("migration").setLevel(logging.INFO)
        logging.getLogger("loader").setLevel(logging.INFO)

        # create or load the profile object. allow test to override profile.
        is_created = False
        if not profile:
            # determine the profile_path
            if profile_dir:
                profile_path = profile_dir / pathlib.Path("Profile").with_suffix(".nsproj")
            else:
                data_dir = pathlib.Path(self.ui.get_data_location())
                profile_name = pathlib.Path(self.ui.get_persistent_string("profile_name", "Profile"))
                profile_path = data_dir / profile_name.with_suffix(".nsproj")
            # create the profile
            profile, is_created = self.__establish_profile(profile_path)
        self.__profile = profile

        # if it was created, it probably means it is migrating from an old version. so add all recent projects.
        # they will initially be disabled and the user will have to explicitly upgrade them.
        if is_created:
            for library_path in self.get_recent_library_paths():
                logging.getLogger("loader").info(f"Adding legacy project {library_path}")
                profile.add_project_folder(pathlib.Path(library_path), load=False)

        # configure the document model object.
        DocumentModel.DocumentModel.computation_min_period = 0.1
        DocumentModel.DocumentModel.computation_min_factor = 1.0

        project_reference: typing.Optional[Profile.ProjectReference] = None

        project_reference = project_reference or profile.get_project_reference(profile.last_project_reference)

        # for backwards compatibility for beta versions. remove after limited beta sites updated.
        project_reference = project_reference or profile.get_project_reference(profile.work_project_reference_uuid)

        if project_reference:
            try:
                document_controller = self.open_project_window(project_reference)
            except Exception:
                self.show_ok_dialog(_("Error Opening Project"), _("Unable to open default project."), completion_fn=self.show_open_project_dialog)
                return True

            if profile_dir is None:
                # output log message unless we passed a profile_dir for testing.
                logging.getLogger("loader").info("Welcome to Nion Swift.")

            if is_created and len(document_controller.document_model.display_items) > 0:
                document_controller.selected_display_panel.set_display_panel_display_item(document_controller.document_model.display_items[0])
                document_controller.selected_display_panel.perform_action("set_fill_mode")
        else:
            self.show_open_project_dialog()

        return True

    def open_project_manager(self) -> None:
        if not self.is_dialog_type_open(ProjectPanel.ProjectDialog):
            project_dialog = ProjectPanel.ProjectDialog(self.ui, self)
            project_dialog.show()

    def open_project_window(self, project_reference: Profile.ProjectReference) -> DocumentController.DocumentController:
        self.__profile.read_project(project_reference)

        document_model = project_reference.document_model
        document_model.create_default_data_groups()
        document_model.start_dispatcher()

        # create the document controller
        document_controller = self.create_document_controller(document_model, "library")

        self.__profile.last_project_reference = project_reference.uuid
        project_reference.last_used = datetime.datetime.now()

        def window_closed():
            pass # print(f"CLOSED {document_controller.title}")

        document_controller.on_close = window_closed

        return document_controller

    def show_open_project_dialog(self) -> None:
        ui = self.ui
        filter = "Projects (*.nsproj);;Legacy Libraries (*.nslib);;All Files (*.*)"
        import_dir = ui.get_persistent_string("open_directory", ui.get_document_location())
        paths, selected_filter, selected_directory = ui.get_file_paths_dialog(_("Add Existing Library"), import_dir, filter)
        ui.set_persistent_string("open_directory", selected_directory)
        if len(paths) == 1:
            project_reference = self.profile.open_project(pathlib.Path(paths[0]))
            if project_reference:
                self.open_project_reference(project_reference)
            else:
                self.show_ok_dialog(_("Error Opening Project"), _("Unable to open project."), completion_fn=self.show_open_project_dialog)

    def get_recent_library_paths(self):
        workspace_history = self.ui.get_persistent_object("workspace_history", list())
        return [file_path for file_path in workspace_history if os.path.exists(file_path)]

    def create_document_controller(self, document_model, workspace_id, display_item=None):
        self._set_document_model(document_model)  # required to allow API to find document model
        document_controller = DocumentController.DocumentController(self.ui, document_model, workspace_id=workspace_id, app=self)
        self.document_model_available_event.fire(document_model)
        # attempt to set data item / group
        if display_item:
            display_panel = document_controller.selected_display_panel
            if display_panel:
                display_panel.set_display_panel_display_item(display_item)
        document_controller._dynamic_recent_project_actions = []
        document_controller.show()
        return document_controller

    def _set_profile_for_test(self, profile: Profile.Profile) -> None:
        self.__profile = profile

    def __establish_profile(self, profile_path: pathlib.Path) -> typing.Tuple[typing.Optional[Profile.Profile], bool]:
        assert profile_path.is_absolute()  # prevents tests from creating temporary files in test directory
        create_new_profile = not profile_path.exists()
        if create_new_profile:
            logging.getLogger("loader").info(f"Creating new profile {profile_path}")
            profile_json = json.dumps({"version": FileStorageSystem.PROFILE_VERSION, "uuid": str(uuid.uuid4())})
            profile_path.write_text(profile_json, "utf-8")
        else:
            logging.getLogger("loader").info(f"Using existing profile {profile_path}")
        storage_system = FileStorageSystem.FilePersistentStorageSystem(profile_path)
        storage_system.load_properties()
        cache_path = profile_path.parent / pathlib.Path(profile_path.stem + " Cache").with_suffix(".nscache")
        logging.getLogger("loader").info(f"Using cache {cache_path}")
        storage_cache = Cache.DbStorageCache(cache_path)
        profile = Profile.Profile(storage_system=storage_system, storage_cache=storage_cache)
        profile.read_profile()
        return profile, create_new_profile

    @property
    def document_controllers(self) -> typing.List[DocumentController.DocumentController]:
        return typing.cast(typing.List[DocumentController.DocumentController], self.windows)

    def register_menu_handler(self, new_menu_handler):
        assert new_menu_handler not in self.__menu_handlers
        self.__menu_handlers.append(new_menu_handler)
        # when a menu handler is registered, let it immediately know about existing menu handlers
        for document_controller in self.windows:
            new_menu_handler(document_controller)
        # return the menu handler so that it can be used to unregister (think: lambda)
        return new_menu_handler

    def unregister_menu_handler(self, menu_handler):
        self.__menu_handlers.remove(menu_handler)

    @property
    def menu_handlers(self) -> typing.List:
        return copy.copy(self.__menu_handlers)

    def _menu_about_to_show(self, window: UIWindow.Window, menu: UserInterface.Menu) -> bool:
        if menu.menu_id == "recent_projects":
            self.__about_to_show_recent_projects_menu(window, menu)
            return True
        return super()._menu_about_to_show(window, menu)

    def __about_to_show_recent_projects_menu(self, window: UIWindow.Window, menu: UserInterface.Menu) -> None:
        # recent project actions are stored with the window so they can be deleted.
        if hasattr(window, "_dynamic_recent_project_actions"):
            for recent_project_action in window._dynamic_recent_project_actions:
                menu.remove_action(recent_project_action)
        window._dynamic_recent_project_actions = []
        project_references = filter(lambda pr: pr.project_state != "loaded", self.__profile.project_references)
        project_references = sorted(project_references, key=operator.attrgetter("last_used"), reverse=True)
        for project_reference in project_references[:20]:
            if project_reference.project_state != "loaded":
                project_title = project_reference.title
                if project_reference.project_version != FileStorageSystem.PROJECT_VERSION:
                    project_title += " " + _("(NEEDS UPGRADE)")
                action = menu.add_menu_item(project_title, functools.partial(self.open_project_reference, project_reference))
                window._dynamic_recent_project_actions.append(action)

    def create_project_reference(self, directory: pathlib.Path, project_name: str) -> None:
        project_reference = self.profile.create_project(directory, project_name)
        if project_reference:
            self.switch_project_reference(project_reference)

    def open_project_reference(self, project_reference: Profile.ProjectReference) -> None:
        if project_reference.project_version == FileStorageSystem.PROJECT_VERSION and project_reference.project_state == "unloaded":
            self.switch_project_reference(project_reference)
        elif project_reference.project_state == "needs_upgrade":
            def handle_upgrade(result: bool) -> None:
                if result:
                    try:
                        new_project_reference = self.profile.upgrade(project_reference)
                    except Exception:
                        self.show_ok_dialog(_("Error Upgrading Project"), _("Unable to upgrade project."))
                        new_project_reference = None
                    if new_project_reference:
                        self.switch_project_reference(new_project_reference)

            self.show_ok_cancel_dialog(_("Project Needs Upgrade"),
                                       _("This project needs to be upgraded to work with this version."),
                                       ok_text=_("Upgrade"),
                                       completion_fn=handle_upgrade)
        else:
            self.show_ok_dialog(_("Error Opening Project"), _("Unable to open project."), completion_fn=self.show_open_project_dialog)

    def switch_project_reference(self, project_reference: Profile.ProjectReference) -> None:
        for window in self.windows:
            if isinstance(window, DocumentController.DocumentController):
                window.request_close()
        try:
            self.open_project_window(project_reference)
        except Exception:
            self.show_ok_dialog(_("Error Opening Project"), _("Unable to open project."), completion_fn=self.show_open_project_dialog)

    def run_all_tests(self):
        Test.run_all_tests()


def get_root_dir():
    root_dir = os.path.dirname((os.path.dirname(os.path.abspath(__file__))))
    path_ascend_count = 2
    for i in range(path_ascend_count):
        root_dir = os.path.dirname(root_dir)
    return root_dir


class NewProjectAction(UIWindow.Action):
    action_id = "project.new_project"
    action_name = _("New Project...")

    def invoke(self, context: UIWindow.ActionContext) -> UIWindow.ActionResult:
        context = typing.cast(DocumentController.DocumentController.ActionContext, context)

        class NewProjectDialog(Dialog.ActionDialog):

            def __init__(self, ui, app: Application, event_loop: asyncio.AbstractEventLoop, profile: Profile.Profile):
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
                    event_loop.call_soon(self.request_close)

                def handle_new_and_close():
                    app.create_project_reference(pathlib.Path(self.directory), self.__project_name_field.text)
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
                self.add_button(_("Create Project"), handle_new_and_close)

                self.content.add(column)

                self.__project_name_field = project_name_field

            def show(self, *, size: Geometry.IntSize = None, position: Geometry.IntPoint = None) -> None:
                super().show(size=size, position=position)
                self.__project_name_field.focused = True
                self.__project_name_field.select_all()

        application = typing.cast(Application, context.application)
        new_project_dialog = NewProjectDialog(application.ui, application, application.event_loop, application.profile)
        new_project_dialog.show()

        return UIWindow.ActionResult.FINISHED


class OpenProjectAction(UIWindow.Action):
    action_id = "project.open_project"
    action_name = _("Open Project...")

    def invoke(self, context_: UIWindow.ActionContext) -> UIWindow.ActionResult:
        context = typing.cast(DocumentController.DocumentController.ActionContext, context_)
        application = typing.cast(Application, context.application)
        application.show_open_project_dialog()
        return UIWindow.ActionResult.FINISHED


UIWindow.register_action(NewProjectAction())
UIWindow.register_action(OpenProjectAction())
