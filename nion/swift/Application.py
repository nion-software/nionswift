from __future__ import annotations

# standard libraries
import asyncio
import datetime
import functools
import gettext
import json
import logging
import operator
import os
import pathlib
import pkgutil
import re
import sys
import typing
import urllib.parse
import uuid
import webbrowser

# third party libraries
# None

# local libraries
from nion.swift import ActivityPanel
from nion.swift import DataPanel
from nion.swift import DocumentController
from nion.swift import FilterPanel
from nion.swift import HistogramPanel
from nion.swift import InfoPanel
from nion.swift import Inspector
from nion.swift import MetadataPanel
from nion.swift import NotificationDialog
from nion.swift import Panel
from nion.swift import ProjectPanel
from nion.swift import SessionPanel
from nion.swift import Task
from nion.swift import ToolbarPanel
from nion.swift import Workspace
from nion.swift.model import ApplicationData
from nion.swift.model import ColorMaps
from nion.swift.model import DocumentModel
from nion.swift.model import FileStorageSystem
from nion.swift.model import PlugInManager
from nion.swift.model import Profile
from nion.swift.model import Symbolic
from nion.ui import Application as UIApplication
from nion.ui import CanvasItem
from nion.ui import Declarative
from nion.ui import Dialog
from nion.ui import UserInterface
from nion.ui import Window as UIWindow
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Model
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.swift.model import DisplayItem

_ = gettext.gettext

app: Application = typing.cast("Application", None)


class PersistenceHandler(UserInterface.PersistenceHandler):
    # handle persistent values using a file instead of ui-tool.

    def get_string(self, key: str) -> typing.Tuple[bool, str]:
        application_data = ApplicationData.get_data()
        values = application_data.get("preference-values", dict())
        if key in values:
            return True, values.get(key)
        return False, str()

    def set_string(self, key: str, value: str) -> bool:
        application_data = ApplicationData.get_data()
        values = application_data.setdefault("preference-values", dict())
        values[key] = value
        ApplicationData.set_data(application_data)
        return True

    def remove_key(self, key: str) -> bool:
        application_data = ApplicationData.get_data()
        values = application_data.get("preference-values", dict())
        if key in values:
            values.pop(key)
            ApplicationData.set_data(application_data)
            return True
        return False


class AboutDialog(Dialog.OkCancelDialog):
    def __init__(self, ui: UserInterface.UserInterface, parent_window: UIWindow.Window, version_str: str):
        super().__init__(ui, include_cancel=False, parent_window=parent_window)

        class Handler(Declarative.Handler):
            def __init__(self) -> None:
                super().__init__()

                logo_png = pkgutil.get_data(__name__, "resources/Logo3.png")
                assert logo_png is not None

                self.icon = CanvasItem.load_rgba_data_from_bytes(logo_png)

                changes_json_data = pkgutil.get_data(__name__, "resources/changes.json")
                assert changes_json_data is not None
                changes_data: typing.Sequence[typing.Mapping[str, typing.Any]] = json.loads(changes_json_data)

                u = Declarative.DeclarativeUI()

                base_prefix_label = [u.create_spacing(13), u.create_label(text=sys.base_prefix)] if sys.base_prefix else [u.create_spacing(0)]

                package_names = []
                package_versions = []

                for __, package_name, package_version in Application.get_nion_swift_version_info():
                    package_names.append(u.create_label(text=package_name))
                    package_versions.append(u.create_label(text=package_version))

                self.markdown = str()

                for version_d in changes_data:
                    changes_version_str = version_d["version"]
                    release_date_str = version_d.get("release_date")
                    self.markdown += "\n" + "### " + changes_version_str + (f" ({release_date_str})" if release_date_str else "") + "\n"
                    for notes_d in version_d.get("notes", list()):
                        summary_line = notes_d["summary"]
                        issue_thunks = list()
                        for issue_url in notes_d.get("issues", list()):
                            numbers = re.findall(r"\d+", issue_url)
                            if numbers:
                                issue_number = numbers[-1]
                                issue_thunks.append(f"[#{issue_number}]({issue_url})")
                        if issue_thunks:
                            summary_line += " (" + ", ".join(issue_thunks) + ")"
                        author_thunks = list()
                        for author_d in notes_d.get("authors", list()):
                            author = author_d.get("github")
                            if author:
                                author_thunks.append(f"[{author}](https://github.com/{author})")
                        if author_thunks:
                            summary_line += " by " + ", ".join(author_thunks)
                        self.markdown += "* " + summary_line + "\n"

                packages_scroll_area = u.create_scroll_area(u.create_row(u.create_column(*package_names), u.create_spacing(8),
                                                         u.create_column(*package_versions), u.create_stretch(),
                                                         spacing=8))
                icon_column = u.create_column(u.create_image(image="icon", width=72, height=72), u.create_stretch(), margin=4, spacing=8)
                main_content_column = u.create_column(u.create_label(text=f"Nion Swift {version_str}"),
                                                      u.create_label(text="© 2012-2023 Nion Company. All Rights Reserved."),
                                                      u.create_spacing(13),
                                                      u.create_label(text=f"Python {sys.version}", word_wrap=True),
                                                      *base_prefix_label, packages_scroll_area, u.create_stretch(),
                                                      margin_top=4,
                                                      margin_bottom=4,
                                                      spacing=8)
                recent_changes_content_column = u.create_column(u.create_scroll_area(u.create_column(
                    u.create_text_browser(markdown="@binding(markdown)", on_anchor_clicked="handle_anchor_clicked", size_policy_vertical="expanding"))))
                main_tabs = u.create_tabs(
                    u.create_tab(label=_("About"), content=main_content_column),
                    u.create_tab(label=_("Recent Changes"), content=recent_changes_content_column),
                    style="minimal"
                )
                self.ui_view = u.create_column(
                    u.create_row(
                        icon_column,
                        main_tabs,
                        spacing=8,
                        margin=6
                    ),
                    min_width=640,
                    min_height=300
                )

            def handle_anchor_clicked(self, widget: Declarative.UIWidget, anchor: str) -> bool:
                o = urllib.parse.urlparse(anchor)
                if o.scheme in ("http", "https"):
                    webbrowser.open(anchor)
                    return True
                return False

        self.content.add(Declarative.DeclarativeWidget(ui, self.event_loop or asyncio.get_event_loop(), Handler()))


# facilitate bootstrapping the application
class Application(UIApplication.BaseApplication):
    count = 0  # useful for detecting leaks in tests

    def __init__(self, ui: UserInterface.UserInterface, set_global: bool = True) -> None:
        super().__init__(ui)
        self.__class__.count += 1

        # reset these values for tests. otherwise tests run slower after app.start is called in any previous test.
        Symbolic.computation_min_period = 0.0
        Symbolic.computation_min_factor = 0.0

        logging.getLogger("migration").setLevel(logging.ERROR)
        logging.getLogger("loader").setLevel(logging.ERROR)

        ui.set_application_info("Nion Swift", "Nion", "nion.com")

        ui.set_persistence_handler(PersistenceHandler())
        setattr(self.ui, "persistence_root", "3")  # sets of preferences
        self.version_str = "16.11.0"

        self.document_model_available_event = Event.Event()

        global app
        app = self  # hack to get the single instance set. hmm. better way?

        self.__profile: typing.Optional[Profile.Profile] = None
        self.__document_model: typing.Optional[DocumentModel.DocumentModel] = None

        self.__menu_handlers: typing.List[typing.Callable[[DocumentController.DocumentController], None]] = []

        Registry.register_component(Inspector.DeclarativeImageChooserConstructor(self), {"declarative_constructor"})
        Registry.register_component(Inspector.DeclarativeDataSourceChooserConstructor(self), {"declarative_constructor"})

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
        workspace_manager.register_panel(ActivityPanel.ActivityPanel, "activity-panel", _("Activity"), ["left", "right"], "right", {"min-width": 320, "height": 80})
        workspace_manager.register_filter_panel(FilterPanel.FilterPanel)

    def initialize(self, *, load_plug_ins: bool = True, use_root_dir: bool = True) -> None:
        super().initialize()
        NotificationDialog._app = self
        # configure app data
        if load_plug_ins:
            logging.info("Launch time " + str(datetime.datetime.now()))
            logging.info("Python version " + str(sys.version.replace('\n', '')))
            logging.info("User interface class " + type(self.ui).__name__ + " / " + type(getattr(self.ui, "proxy")).__name__)
            logging.info("Qt version " + self.ui.get_qt_version())
            app_data_file_path = self.ui.get_configuration_location() / pathlib.Path("nionswift_appdata.json")
            ApplicationData.set_file_path(app_data_file_path)
            logging.info("Application data: " + str(app_data_file_path))
            PlugInManager.load_plug_ins(self.ui.get_document_location(), self.ui.get_data_location(), get_root_dir() if use_root_dir else None)
            color_maps_dir = self.ui.get_configuration_location() / pathlib.Path("Color Maps")
            if color_maps_dir.exists():
                logging.info("Loading color maps from " + str(color_maps_dir))
                ColorMaps.load_color_maps(color_maps_dir)
            else:
                logging.info("NOT Loading color maps from " + str(color_maps_dir) + " (missing)")
        Registry.register_component(self, {"application"})

    def deinitialize(self) -> None:
        # shut down hardware source manager, unload plug-ins, and really exit ui
        NotificationDialog.close_notification_dialog()
        Registry.unregister_component(self, {"application"})
        if self.__profile:
            self.__profile.close()
            self.__profile = None
        self.__document_model = None
        PlugInManager.unload_plug_ins()
        global app
        app = typing.cast(Application, None)  # hack to get the single instance set. hmm. better way?
        self.__class__.count -= 1
        super().deinitialize()

    @property
    def profile(self) -> Profile.Profile:
        assert self.__profile
        return self.__profile

    @property
    def document_model(self) -> DocumentModel.DocumentModel:
        assert self.__document_model
        return self.__document_model

    # for testing
    def _set_document_model(self, document_model: DocumentModel.DocumentModel) -> None:
        self.__document_model = document_model

    def start(self, *, profile_dir: typing.Optional[pathlib.Path] = None, profile: typing.Optional[Profile.Profile] = None) -> bool:
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
        assert self.__profile

        # test code to reset script items
        # self.__profile.script_items_updated = False
        # while self.__profile.script_items:
        #     self.__profile.remove_script_item(self.__profile.script_items[-1])

        # migrate the interactive scripts persistent object
        if not self.__profile.script_items_updated:
            items_str = self.ui.get_persistent_string("interactive_scripts_1")
            if items_str:
                for item_dict in json.loads(items_str):
                    item_type = item_dict.get("__type__", None)
                    if item_type == "FolderListItem":
                        folder_path_str = item_dict.get("full_path", None)
                        folder_path = pathlib.Path(folder_path_str) if folder_path_str else None
                        if folder_path:
                            self.__profile.append_script_item(Profile.FolderScriptItem(pathlib.Path(folder_path)))
                    elif item_type == "ScriptListItem" and item_dict.get("indent_level", None) == 0:
                        script_path_str = item_dict.get("full_path", None)
                        script_path = pathlib.Path(script_path_str) if script_path_str else None
                        if script_path:
                            self.__profile.append_script_item(Profile.FileScriptItem(pathlib.Path(script_path)))
            else:
                items_old = self.ui.get_persistent_object("interactive_scripts_0", list())
                for script_path_str in items_old:
                    script_path = pathlib.Path(script_path_str) if script_path_str else None
                    if script_path:
                        self.__profile.append_script_item(Profile.FileScriptItem(pathlib.Path(script_path)))
            self.__profile.script_items_updated = True

        # configure the document model object.
        Symbolic.computation_min_period = 0.1
        Symbolic.computation_min_factor = 1.0

        # if it was created, it probably means it is migrating from an old version. so add all recent projects.
        # they will initially be disabled and the user will have to explicitly upgrade them.
        if is_created:
            # present a dialog for showing progress while finding existing projects
            u = Declarative.DeclarativeUI()
            task_message = u.create_label(text=_("Looking for existing projects..."))
            progress = u.create_progress_bar(value="@binding(progress_value_model.value)", width=300 - 24)
            progress_message = u.create_label(text="@binding(message_str_model.value)")
            main_column = u.create_column(task_message, progress, progress_message, spacing=8, width=300)
            window = u.create_window(main_column, title=_("Locating Existing Projects"), margin=12, window_style="tool")

            # handler for the progress window. defines two value models: progress, an int 0-100; and message, a string.
            class FindExistingProjectsWindowHandler(Declarative.WindowHandler):
                def __init__(self, *, completion_fn: typing.Optional[typing.Callable[[], None]] = None):
                    super().__init__(completion_fn=completion_fn)
                    self.progress_value_model = Model.PropertyModel(0)
                    self.message_str_model = Model.PropertyModel(str())

            # construct the window handler and run it. when the dialog closes, it will continue by
            # calling open default project.
            def complete_find_existing_projects() -> None:
                self.__open_default_project(profile_dir, is_created)

            window_handler = FindExistingProjectsWindowHandler(completion_fn=complete_find_existing_projects)
            window_handler.run(window, app=self)

            # define an async routine that will perform the finding of the existing projects.
            # this is just a loop that yields via asyncio.sleep periodically. the loop loads
            # the projects and updates the progress and message value models in the dialog.
            # when finished, it asks the window to close on its next periodic call. it is
            # necessary to close this way because the close request may close the event loop
            # in which we're executing. so queueing the close request avoids that.
            async def find_existing_projects() -> None:
                recent_library_paths = self.get_recent_library_paths()
                for index, library_path in enumerate(recent_library_paths):
                    window_handler.progress_value_model.value = 100 * index // len(recent_library_paths)
                    window_handler.message_str_model.value = str(library_path.name)
                    logging.getLogger("loader").info(f"Adding existing project {index + 1}/{len(recent_library_paths)} {library_path}")
                    await asyncio.sleep(0)
                    assert self.__profile
                    self.__profile.add_project_folder(pathlib.Path(library_path), load=False)
                window_handler.progress_value_model.value = 100
                window_handler.message_str_model.value = _("Finished")
                await asyncio.sleep(1)
                window_handler.window.queue_request_close()

            # launch the find existing projects task asynchronously.
            window_handler.window.event_loop.create_task(find_existing_projects())
            return True
        else:
            # continue with opening the default project
            return self.__open_default_project(profile_dir, is_created)

    def __open_default_project(self, profile_dir: typing.Optional[pathlib.Path], is_created: bool) -> bool:
        # if the default project is known, open it.
        # if it fails, ask the user to select another project.
        # if no default project is known, ask the user to choose one.

        profile = self.profile

        project_reference: typing.Optional[Profile.ProjectReference] = None

        if not project_reference:
            project_reference = profile.get_project_reference(profile.last_project_reference) if profile.last_project_reference else None

        update_last_project_reference = True

        keyboard_modifiers = self.ui.get_keyboard_modifiers(True)
        if keyboard_modifiers and keyboard_modifiers.shift:  # pass True since there has been no event yet
            project_reference = None
            update_last_project_reference = False

        if project_reference and project_reference.is_valid:
            try:
                document_controller = self.open_project_window(project_reference, update_last_project_reference)
            except Exception:
                self.show_ok_dialog(_("Error Opening Project"), _("Unable to open default project."), completion_fn=self.show_choose_project_dialog)
                return True

            if profile_dir is None:
                # output log message unless we passed a profile_dir for testing.
                logging.getLogger("loader").info("Welcome to Nion Swift.")

            selected_display_panel = document_controller.selected_display_panel
            if selected_display_panel and is_created and len(document_controller.document_model.display_items) > 0:
                selected_display_panel.set_display_panel_display_item(document_controller.document_model.display_items[0])
                selected_display_panel.perform_action("set_fill_mode")
        else:
            self.show_choose_project_dialog()

        return True

    def open_project_manager(self) -> None:
        if not self.is_dialog_type_open(ProjectPanel.ProjectDialog):
            project_dialog = ProjectPanel.ProjectDialog(self.ui, self)
            project_dialog.show()

    def open_project_window(self, project_reference: Profile.ProjectReference, update_last_project_reference: bool = True) -> DocumentController.DocumentController:
        assert self.__profile

        self.__profile.read_project(project_reference)

        document_model = project_reference.document_model
        assert document_model

        document_model.create_default_data_groups()
        document_model.start_dispatcher()

        # create the document controller
        document_controller = self.create_document_controller(document_model, "library", project_reference=project_reference)

        if update_last_project_reference:
            self.__profile.last_project_reference = project_reference.uuid

        project_reference.last_used = datetime.datetime.now()

        return document_controller

    def show_open_project_dialog(self) -> None:
        profile = self.profile
        with self.prevent_close():
            ui = self.ui
            filter_str = "Projects (*.nsproj);;Legacy Libraries (*.nslib);;All Files (*.*)"
            import_dir = ui.get_persistent_string("open_directory", ui.get_document_location())
            paths, selected_filter, selected_directory = ui.get_file_paths_dialog(_("Add Existing Library"), import_dir, filter_str)
            if len(paths) == 1:
                ui.set_persistent_string("open_directory", selected_directory)
                project_reference = profile.open_project(pathlib.Path(paths[0]))
                if project_reference:
                    self.open_project_reference(project_reference)
                else:
                    self.show_ok_dialog(_("Error Opening Project"), _("Unable to open project."), completion_fn=self.show_choose_project_dialog)

    def show_choose_project_dialog(self) -> None:
        with self.prevent_close():
            u = Declarative.DeclarativeUI()
            button_row = u.create_row(u.create_push_button(text=_("New..."), on_clicked="new_project"),
                                      u.create_push_button(text=_("Open..."), on_clicked="open_project"),
                                      u.create_stretch(),
                                      u.create_push_button(text=_("Cancel"), on_clicked="close_window"),
                                      u.create_push_button(text=_("Open Selected"), on_clicked="open_recent"),
                                      spacing=8)

            project_references_model = ListModel.FilteredListModel(container=self.__profile, items_key="project_references")
            project_references_model.filter = ListModel.PredicateFilter(lambda pr: bool(pr.project_state != "loaded"))
            project_references_model.sort_key = lambda pr: pr.recents_key
            project_references_model.sort_reverse = True

            class ProjectReferenceItem:
                # provides a str converter and a tool tip.
                def __init__(self, project_reference: Profile.ProjectReference):
                    self.project_reference = project_reference

                def __str__(self) -> str:
                    project_reference = self.project_reference
                    project_title = project_reference.title or str()
                    project_title += " [" + (project_reference.last_used or project_reference.modified).strftime('%Y-%m-%d') + "]"
                    if project_reference.project_state == "needs_upgrade":
                        project_title += " " + _("(NEEDS UPGRADE)")
                    elif project_reference.project_state == "missing":
                        project_title += " " + _("(MISSING)")
                    elif project_reference.project_state != "unloaded" or project_reference.project_version != FileStorageSystem.PROJECT_VERSION:
                        project_title += " " + _("(UNREADABLE)")
                    return project_title

                @property
                def tool_tip(self) -> str:
                    return str(self.project_reference.path)

            project_reference_items_model = ListModel.MappedListModel(container=project_references_model,
                                                                      master_items_key="project_references",
                                                                      items_key="project_reference_items",
                                                                      map_fn=ProjectReferenceItem)

            item_list = u.create_list_box(items_ref="@binding(list_property_model.value)",
                                          current_index="@binding(current_index)",
                                          min_height=180, min_width=240,
                                          size_policy_horizontal="expanding",
                                          size_policy_vertical="expanding",
                                          on_item_selected="recent_item_selected",
                                          on_item_handle_context_menu="item_handle_context_menu")

            main_column = u.create_column(u.create_label(text=_("Recent Projects")),
                                          item_list,
                                          u.create_spacing(13),
                                          button_row, spacing=8, min_width=360)
            window = u.create_window(main_column, title=_("Choose Project"), margin=12, window_style="tool")

            def open_project_reference(project_reference: Profile.ProjectReference) -> None:
                self.open_project_reference(project_reference)

            def show_open_project_dialog() -> None:
                self.show_open_project_dialog()

            def show_new_project_dialog() -> None:
                NewProjectAction().invoke(UIWindow.ActionContext(self, None, None))

            class ChooseProjectHandler(Declarative.WindowHandler):
                def __init__(self, application: Application):
                    super().__init__()
                    self.__application = application
                    self.current_index = 0
                    self.list_property_model = ListModel.ListPropertyModel(project_reference_items_model)

                def recent_item_selected(self, widget: Declarative.UIWidget, current_index: int) -> None:
                    if 0 <= current_index < len(project_reference_items_model.project_reference_items):
                        # to ensure the application does not close upon closing the last window, force it
                        # to stay open while the window is closed and another reopened.
                        with self.__application.prevent_close():
                            self.close_window()
                            project_reference_item = project_reference_items_model.project_reference_items[current_index]
                            open_project_reference(project_reference_item.project_reference)

                def new_project(self, widget: Declarative.UIWidget) -> None:
                    # to ensure the application does not close upon closing the last window, force it
                    # to stay open while the window is closed and another reopened.
                    with self.__application.prevent_close():
                        show_new_project_dialog()
                        self.close_window()

                def open_project(self, widget: Declarative.UIWidget) -> None:
                    # to ensure the application does not close upon closing the last window, force it
                    # to stay open while the window is closed and another reopened.
                    with self.__application.prevent_close():
                        show_open_project_dialog()
                        self.close_window()

                def open_recent(self, widget: Declarative.UIWidget) -> None:
                    self.recent_item_selected(widget, self.current_index)

                def item_handle_context_menu(self, widget: Declarative.UIWidget, *,
                                             gx: int, gy: int,
                                             index: typing.Optional[int], **kwargs: typing.Any) -> bool:
                    if index is not None:
                        project_reference_item = project_reference_items_model.project_reference_items[index]
                        menu = self.window.create_context_menu()
                        menu.add_menu_item(_(f"Open Project Location"), functools.partial(ProjectPanel.reveal_project, project_reference_item.project_reference))
                        menu.add_separator()

                        def remove_project(index: int) -> None:
                            project_reference_item = project_reference_items_model.project_reference_items[index]
                            profile = self.__application.profile
                            profile.remove_project_reference(project_reference_item.project_reference)

                        menu.add_menu_item(_(f"Remove Project from List"), functools.partial(remove_project, index))
                        menu.popup(gx, gy)
                    return True

            ChooseProjectHandler(self).run(window, app=self, persistent_id="choose_project")

    def get_recent_library_paths(self) -> typing.List[pathlib.Path]:
        workspace_history = self.ui.get_persistent_object("workspace_history", list())
        return [pathlib.Path(file_path) for file_path in workspace_history if os.path.exists(file_path)]

    def create_document_controller(self, document_model: DocumentModel.DocumentModel, workspace_id: str,
                                   display_item: typing.Optional[DisplayItem.DisplayItem] = None,
                                   project_reference: typing.Optional[Profile.ProjectReference] = None) -> DocumentController.DocumentController:
        self._set_document_model(document_model)  # required to allow API to find document model
        document_controller = DocumentController.DocumentController(self.ui, document_model, workspace_id=workspace_id,
                                                                    app=self, project_reference=project_reference)
        self.document_model_available_event.fire(document_model)
        # attempt to set data item / group
        if display_item:
            display_panel = document_controller.selected_display_panel
            if display_panel:
                display_panel.set_display_panel_display_item(display_item)
        setattr(document_controller, "_dynamic_recent_project_actions", list())
        document_controller.show()
        return document_controller

    def _set_profile_for_test(self, profile: typing.Optional[Profile.Profile]) -> None:
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
        storage_system = FileStorageSystem.make_file_persistent_storage_system(profile_path)
        storage_system.load_properties()
        old_cache_path = profile_path.parent / pathlib.Path(profile_path.stem + " Cache").with_suffix(".nscache")
        if old_cache_path.exists():
            logging.getLogger("loader").info(f"Removing old cache {old_cache_path}")
            old_cache_path.unlink()
        cache_dir_path = profile_path.parent / "Cache"
        cache_dir_path.mkdir(parents=True, exist_ok=True)
        profile = Profile.Profile(storage_system=storage_system, cache_dir_path=cache_dir_path)
        profile.read_profile()
        return profile, create_new_profile

    @property
    def document_controllers(self) -> typing.List[DocumentController.DocumentController]:
        return typing.cast(typing.List[DocumentController.DocumentController], self.windows)

    def register_menu_handler(self, new_menu_handler: typing.Callable[[DocumentController.DocumentController], None]) -> typing.Callable[[DocumentController.DocumentController], None]:
        assert new_menu_handler not in self.__menu_handlers
        self.__menu_handlers.append(new_menu_handler)
        # when a menu handler is registered, let it immediately know about existing menu handlers
        for document_controller in self.windows:
            new_menu_handler(typing.cast(DocumentController.DocumentController, document_controller))
        # return the menu handler so that it can be used to unregister (think: lambda)
        return new_menu_handler

    def unregister_menu_handler(self, menu_handler: typing.Callable[[DocumentController.DocumentController], None]) -> None:
        self.__menu_handlers.remove(menu_handler)

    @property
    def menu_handlers(self) -> typing.Sequence[typing.Callable[[DocumentController.DocumentController], None]]:
        return list(self.__menu_handlers)

    def _menu_about_to_show(self, window: UIWindow.Window, menu: UserInterface.Menu) -> bool:
        if menu.menu_id == "recent_projects":
            self.__about_to_show_recent_projects_menu(window, menu)
            return True
        return super()._menu_about_to_show(window, menu)

    def __about_to_show_recent_projects_menu(self, window: UIWindow.Window, menu: UserInterface.Menu) -> None:
        # recent project actions are stored with the window so they can be deleted.
        if hasattr(window, "_dynamic_recent_project_actions"):
            for recent_project_action in getattr(window, "_dynamic_recent_project_actions"):
                menu.remove_action(recent_project_action)
        setattr(window, "_dynamic_recent_project_actions", list())
        profile = self.profile
        project_references: typing.List[Profile.ProjectReference] = list(filter(lambda pr: pr.project_state != "loaded", profile.project_references))
        project_references = sorted(project_references, key=operator.attrgetter("recents_key"), reverse=True)
        for project_reference in project_references[:20]:
            if project_reference.project_state != "loaded":
                project_title = project_reference.title
                project_title += " [" + (project_reference.last_used or project_reference.modified).strftime('%Y-%m-%d') + "]"
                if project_reference.project_state == "needs_upgrade":
                    project_title += " " + _("(NEEDS UPGRADE)")
                elif project_reference.project_state == "missing":
                    project_title += " " + _("(MISSING)")
                elif project_reference.project_state != "unloaded" or project_reference.project_version != FileStorageSystem.PROJECT_VERSION:
                    project_title += " " + _("(UNREADABLE)")
                action = menu.add_menu_item(project_title, functools.partial(self.open_project_reference, project_reference))
                getattr(window, "_dynamic_recent_project_actions").append(action)

    def create_project_reference(self, directory: pathlib.Path, project_name: str) -> None:
        profile = self.profile
        project_reference = profile.create_project(directory, project_name)
        if project_reference:
            self.switch_project_reference(project_reference)

    def open_project_reference(self, project_reference: Profile.ProjectReference) -> None:
        with self.prevent_close():
            if project_reference.project_version == FileStorageSystem.PROJECT_VERSION and project_reference.project_state == "unloaded":
                self.switch_project_reference(project_reference)
            elif project_reference.project_state == "needs_upgrade":
                def handle_upgrade(result: bool) -> None:
                    profile = self.profile
                    if result and profile:
                        try:
                            new_project_reference = profile.upgrade(project_reference)
                        except FileExistsError:
                            message = _("Upgraded project already exists.")
                            self.show_ok_dialog(_("Error Upgrading Project"), f"{message}\n{project_reference.path}")
                            logging.getLogger("loader").info(f"Project already exists: {project_reference.path}")
                            new_project_reference = None
                        except Exception as e:
                            self.show_ok_dialog(_("Error Upgrading Project"), _("Unable to upgrade project."))
                            import traceback
                            traceback.print_exc()
                            new_project_reference = None
                        if new_project_reference:
                            self.switch_project_reference(new_project_reference)

                self.show_ok_cancel_dialog(_("Project Needs Upgrade"),
                                           _("This project needs to be upgraded to work with this version."),
                                           ok_text=_("Upgrade"),
                                           completion_fn=handle_upgrade)
            else:
                self.show_ok_dialog(_("Error Opening Project"), _("Unable to open project."), completion_fn=self.show_choose_project_dialog)

    def switch_project_reference(self, project_reference: Profile.ProjectReference) -> None:
        for window in self.windows:
            if isinstance(window, DocumentController.DocumentController):
                window.request_close()
        try:
            self.open_project_window(project_reference)
        except Exception:
            self.show_ok_dialog(_("Error Opening Project"), _("Unable to open project."), completion_fn=self.show_choose_project_dialog)

    @classmethod
    def get_nion_swift_version_info(cls) -> typing.List[typing.Tuple[str, str, str]]:
        info = list()
        for path_str in sys.path:
            if path_str.endswith("site-packages"):
                site_packages_path = pathlib.Path(path_str)
                for package in sorted(path.stem for path in site_packages_path.glob("*dist-info")):
                    m = re.match(r"(.*)-(\d+\.\d+.*\d*)", package)
                    g = m.groups() if m else list()
                    if len(g) >= 2:
                        package_name = g[0]
                        package_version = g[1]
                        if package_name.startswith("nion") or package_name in ("python", "scipy", "numpy", "h5py"):
                            info.append((package, package_name, package_version))
        return info

    def show_about_box(self, parent_window: UIWindow.Window) -> None:
        about_dialog = AboutDialog(self.ui, parent_window, self.version_str)
        about_dialog.show()


def get_root_dir() -> str:
    root_dir = os.path.dirname((os.path.dirname(os.path.abspath(__file__))))
    path_ascend_count = 2
    for i in range(path_ascend_count):
        root_dir = os.path.dirname(root_dir)
    return root_dir


class NewProjectAction(UIWindow.Action):
    action_id = "project.new_project"
    action_name = _("New Project...")

    def execute(self, context: UIWindow.ActionContext) -> UIWindow.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: UIWindow.ActionContext) -> UIWindow.ActionResult:
        context = typing.cast(DocumentController.DocumentController.ActionContext, context)

        class NewProjectDialog(Dialog.ActionDialog):

            def __init__(self, ui: UserInterface.UserInterface, app: Application, event_loop: asyncio.AbstractEventLoop, profile: Profile.Profile) -> None:
                super().__init__(ui, title=_("New Project"), app=app, persistent_id="new_project_dialog")

                self.directory = self.ui.get_persistent_string("project_directory", self.ui.get_document_location())

                project_base_name = _("Nion Swift Project") + " " + datetime.datetime.now().strftime("%Y%m%d")
                project_base_index = 0
                project_base_index_str = ""
                while os.path.exists(os.path.join(self.directory, project_base_name + project_base_index_str)):
                    project_base_index += 1
                    project_base_index_str = " " + str(project_base_index)

                self.project_name = project_base_name + project_base_index_str

                def safe_request_close() -> bool:
                    event_loop.call_soon(self.request_close)
                    return True

                def handle_new_and_close() -> bool:
                    app.create_project_reference(pathlib.Path(self.directory), self.__project_name_field.text or "untitled")
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

            def show(self, *, size: typing.Optional[Geometry.IntSize] = None, position: typing.Optional[Geometry.IntPoint] = None) -> None:
                super().show(size=size, position=position)
                self.__project_name_field.focused = True
                self.__project_name_field.select_all()

        application = typing.cast(Application, context.application)
        profile = application.profile
        new_project_dialog = NewProjectDialog(application.ui, application, application.event_loop, profile)
        new_project_dialog.show()

        return UIWindow.ActionResult(UIWindow.ActionStatus.FINISHED)


class OpenProjectAction(UIWindow.Action):
    action_id = "project.open_project"
    action_name = _("Open Project...")

    def execute(self, context: UIWindow.ActionContext) -> UIWindow.ActionResult:
        raise NotImplementedError()

    def invoke(self, context_: UIWindow.ActionContext) -> UIWindow.ActionResult:
        context = typing.cast(DocumentController.DocumentController.ActionContext, context_)
        application = typing.cast(Application, context.application)
        application.show_open_project_dialog()
        return UIWindow.ActionResult(UIWindow.ActionStatus.FINISHED)


class ChooseProjectAction(UIWindow.Action):
    action_id = "project.choose_project"
    action_name = _("Choose Project...")

    def execute(self, context: UIWindow.ActionContext) -> UIWindow.ActionResult:
        raise NotImplementedError()

    def invoke(self, context_: UIWindow.ActionContext) -> UIWindow.ActionResult:
        context = typing.cast(DocumentController.DocumentController.ActionContext, context_)
        application = typing.cast(Application, context.application)
        application.show_choose_project_dialog()
        return UIWindow.ActionResult(UIWindow.ActionStatus.FINISHED)


UIWindow.register_action(NewProjectAction())
UIWindow.register_action(OpenProjectAction())
UIWindow.register_action(ChooseProjectAction())
