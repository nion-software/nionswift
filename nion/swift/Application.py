# standard libraries
import copy
import datetime
import functools
import gettext
import json
import logging
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
from nion.ui import UserInterface
from nion.ui import Window as UIWindow
from nion.utils import Event
from nion.utils import Registry

_ = gettext.gettext

app = None


# facilitate bootstrapping the application
class Application(UIApplication.BaseApplication):

    def __init__(self, ui, set_global=True, resources_path=None):
        super().__init__(ui)

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

        # map these document controller events to listener tokens.
        # when the document controller requests a new document controller,
        # respond in this class by creating a new document controller.
        self.__create_new_event_listeners = dict()

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

    def start(self, *, profile_dir: pathlib.Path = None):
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

        # determine the profile_path
        if profile_dir:
            profile_path = profile_dir / pathlib.Path("Profile").with_suffix(".nsproj")
        else:
            data_dir = pathlib.Path(self.ui.get_data_location())
            profile_name = pathlib.Path(self.ui.get_persistent_string("profile_name", "Profile"))
            profile_path = data_dir / profile_name.with_suffix(".nsproj")

        # create or load the profile object
        self.__profile, is_created = self.__establish_profile(profile_path)
        profile = self.__profile

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

        project_reference = project_reference or profile.get_project_reference(profile.work_project_reference_uuid)

        if project_reference:
            document_controller = self.open_project_window(project_reference)

            if profile_dir is None:
                # output log message unless we passed a profile_dir for testing.
                logging.getLogger("loader").info("Welcome to Nion Swift.")

            if is_created and len(document_controller.document_model.display_items) > 0:
                document_controller.selected_display_panel.set_display_panel_display_item(document_controller.document_model.display_items[0])
                document_controller.selected_display_panel.perform_action("set_fill_mode")
        else:
            self.open_project_manager()

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

        def window_closed():
            pass # print(f"CLOSED {document_controller.title}")

        document_controller.on_close = window_closed

        return document_controller

    def get_recent_library_paths(self):
        workspace_history = self.ui.get_persistent_object("workspace_history", list())
        return [file_path for file_path in workspace_history if os.path.exists(file_path)]

    def create_document_controller(self, document_model, workspace_id, display_item=None):
        self._set_document_model(document_model)  # required to allow API to find document model
        document_controller = DocumentController.DocumentController(self.ui, document_model, workspace_id=workspace_id, app=self)
        self.__create_new_event_listeners[document_controller] = document_controller.create_new_document_controller_event.listen(self.create_document_controller)
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

    def _window_did_close(self, window: UIWindow.Window) -> None:
        # this will be called for _all_ windows, so check if the window is a document window
        # and remove the event listener if required.
        if window in self.__create_new_event_listeners:
            self.__create_new_event_listeners.pop(window).close()
        super()._window_did_close(window)

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
        for project_reference in self.__profile.project_references:
            def open_recent(project_reference: Profile.ProjectReference) -> None:
                for window in self.windows:
                    if isinstance(window, DocumentController.DocumentController):
                        window.request_close()
                self.open_project_window(project_reference)
            project_info = project_reference.project_info
            if project_info[1] == 3 and project_info[2] == "unloaded":
                action = menu.add_menu_item(project_reference.title, functools.partial(open_recent, project_reference))
                window._dynamic_recent_project_actions.append(action)

    def run_all_tests(self):
        Test.run_all_tests()


def get_root_dir():
    root_dir = os.path.dirname((os.path.dirname(os.path.abspath(__file__))))
    path_ascend_count = 2
    for i in range(path_ascend_count):
        root_dir = os.path.dirname(root_dir)
    return root_dir
