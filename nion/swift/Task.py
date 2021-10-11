from __future__ import annotations

# standard libraries
import copy
import gettext
import logging
import threading
import time
import types
import typing

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import Utility
from nion.ui import UserInterface
from nion.utils import Event
from nion.utils import Observable

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import Persistence

_ = gettext.gettext


"""
    Task modules can register task viewer factory with the task manager.

    Tasks will request a new task controller from the document model.

    A task section will get created and added to the task panel with some type of progress
    indicator and cancel button. The task section will display a task viewer if one is
    available for the task data.

    While the task is running, it is free to call task controller methods from
    a thread to update the data. The task controller will take care of getting the
    data to the task viewer on the UI thread.

    When the task finishes, it can optionally send final data. The last data available
    data will get permanently stored into the document.

    When the document loads, all tasks will be displayed in the task panel. The
    user has an option to copy, export, or delete finished tasks.

"""

class TaskPanel(Panel.Panel):

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, _("Tasks"))

        self.__pending_tasks: typing.List[Task] = list()
        self.__pending_tasks_mutex = threading.RLock()

        # thread safe
        def task_created(task: Task) -> None:
            with self.__pending_tasks_mutex:
                self.__pending_tasks.append(task)
                self.document_controller.add_task(str(id(self)), self.__perform_tasks)

        # connect to the document controller
        self.__task_created_event_listener = self.document_controller.task_created_event.listen(task_created)

        # the main column widget contains a stack group for each operation
        self.column = self.ui.create_column_widget(properties=properties)  # TODO: put this in scroll area
        self.scroll_area = self.ui.create_scroll_area_widget()
        self.scroll_area.set_scrollbar_policies("off", "needed")
        self.task_column_container = self.ui.create_column_widget()
        self.task_column = self.ui.create_column_widget()
        self.task_column_container.add(self.task_column)
        self.task_column_container.add_stretch()
        self.scroll_area.content = self.task_column_container
        self.column.add(self.scroll_area)
        self.widget = self.column

        # map task to widgets
        self.__task_needs_update: typing.Set[Task] = set()
        self.__task_needs_update_mutex = threading.RLock()
        self.__task_section_controller_list: typing.List[TaskSectionController] = list()
        self.__task_changed_event_listeners: typing.List[Event.EventListener] = list()

    def close(self) -> None:
        self.document_controller.clear_task(str(id(self)))
        # disconnect to the document controller
        self.__task_created_event_listener.close()
        self.__task_created_event_listener = typing.cast(typing.Any, None)
        # disconnect from tasks
        for task_changed_event_listener in self.__task_changed_event_listeners:
            task_changed_event_listener.close()
        self.__task_changed_event_listeners = typing.cast(typing.Any, None)
        # finish closing
        super().close()

    # not thread safe
    def __perform_tasks(self) -> None:
        # for all pending tasks, make a task section controller, then add the task
        # to the needs update list.
        with self.__pending_tasks_mutex:
            pending_tasks = self.__pending_tasks
            self.__pending_tasks = list()
        for task in pending_tasks:
            task_section_controller = TaskSectionController(self.ui, task)
            self.task_column.insert(task_section_controller.widget, 0)
            self.scroll_area.scroll_to(0, 0)
            self.__task_section_controller_list.append(task_section_controller)
            with self.__task_needs_update_mutex:
                self.__task_needs_update.add(task)

            # thread safe
            def task_changed() -> None:
                with self.__task_needs_update_mutex:
                    self.__task_needs_update.add(task)
                    self.document_controller.add_task(str(id(self)), self.__perform_tasks)

            # TODO: currently, tasks don't get deleted since they are displayed until exit.
            # add the listener to a never deleted list.
            self.__task_changed_event_listeners.append(task.task_changed_event.listen(task_changed))

        # for each started task (i.e. has a section controller), if it needs an
        # update, update it in the section controller.
        for task_section_controller in self.__task_section_controller_list:
            task = task_section_controller.task
            if task in self.__task_needs_update:
                # remove from update list before updating to prevent a race
                with self.__task_needs_update_mutex:
                    self.__task_needs_update.remove(task)
                # update
                task_section_controller.update()
        # finally, if there are tasks that need updating, run perform task again.
        if len(self.__task_needs_update) > 0:
            self.document_controller.add_task(str(id(self)), self.__perform_tasks)


# this is UI object, and not a thread safe
class TaskSectionController:

    def __init__(self, ui: UserInterface.UserInterface, task: Task) -> None:
        self.ui = ui
        self.task = task

        widget = self.ui.create_column_widget()
        task_header = self.ui.create_row_widget()
        self.title_widget = self.ui.create_label_widget()
        self.title_widget.text_font = "bold"
        task_header.add(self.title_widget)
        task_spacer_row = self.ui.create_row_widget()
        task_spacer_row_col = self.ui.create_column_widget()
        task_spacer_row.add_spacing(20)
        task_spacer_row.add(task_spacer_row_col)
        self.task_progress_row = self.ui.create_row_widget()
        self.task_progress_label = self.ui.create_label_widget()
        self.task_progress_row.add(self.task_progress_label)
        task_time_row = self.ui.create_row_widget()
        self.task_progress_state = self.ui.create_label_widget()
        self.task_progress_state.text_font = "italic"
        task_time_row.add(self.task_progress_state)
        task_spacer_row_col.add(self.task_progress_row)
        task_spacer_row_col.add(task_time_row)

        # add custom ui, if any
        self.task_ui_controller = TaskManager().build_task_ui(self.ui, task)
        if self.task_ui_controller:
            task_spacer_row_col.add(self.task_ui_controller.widget)

        widget.add(task_header)
        widget.add(task_spacer_row)

        self.__title_text: typing.Optional[str] = None

        copy_button = self.ui.create_push_button_widget(_("Copy to Clipboard"))
        def copy_to_clipboard() -> None:
            clipboard_text = self.task_ui_controller.clipboard_text if self.task_ui_controller else None
            if clipboard_text:
                if self.__title_text:
                    clipboard_text = self.__title_text + "\n" + clipboard_text
                self.ui.clipboard_set_text(clipboard_text + "\n")
        copy_button.on_clicked = copy_to_clipboard
        copy_button_row = self.ui.create_row_widget()
        copy_button_row.add(copy_button)
        copy_button_row.add_stretch()
        widget.add(copy_button_row)

        self.widget = widget

        self.update()

    # only called on UI thread
    def update(self) -> None:

        # update the title
        self.__title_text = self.task.title.upper()
        self.title_widget.text = self.task.title

        # update the progress label
        in_progress = self.task.in_progress
        if in_progress:
            self.task_progress_label.visible = True
            done_percentage_str = "{0:.0f}%".format(float(self.task.progress[0])/self.task.progress[1] * 100) if self.task.progress else "--"
            progress_text = "{0} {1}".format(done_percentage_str, self.task.progress_text)
            self.task_progress_label.text = progress_text
            self.__title_text += " (" + progress_text + ")"
        else:
            self.task_progress_label.visible = False

        # update the state text
        task_state_str = _("In Progress") if in_progress else _("Done")
        task_time_str = time.strftime("%c", time.localtime(self.task.start_time if in_progress else self.task.finish_time))
        progress_state_text = "{} {}".format(task_state_str, task_time_str)
        self.task_progress_state.text = progress_state_text
        self.__title_text += "\n" + progress_state_text

        # update the custom builder, if any
        if self.task_ui_controller:
            self.task_ui_controller.update_task(self.task)


class Task(Observable.Observable):

    def __init__(self, title: str, task_type: str) -> None:
        super().__init__()
        self.__title = title
        self.__start_time: typing.Optional[float] = None
        self.__finish_time: typing.Optional[float] = None
        self.__task_type = task_type
        self.__task_data: typing.Any = None
        self.__task_data_mutex = threading.RLock()
        self.__progress: typing.Optional[typing.Tuple[int, int]] = None
        self.__progress_text = str()
        self.task_changed_event = Event.Event()

    # title
    @property
    def title(self) -> str:
        return self.__title

    @title.setter
    def title(self, value: str) -> None:
        self.__title = value
        self.notify_property_changed("title")
        self.task_changed_event.fire()

    # start time
    @property
    def start_time(self) -> typing.Optional[float]:
        return self.__start_time

    @start_time.setter
    def start_time(self, value: typing.Optional[float]) -> None:
        self.__start_time = value
        self.notify_property_changed("start_time")
        self.task_changed_event.fire()

    # finish time
    @property
    def finish_time(self) -> typing.Optional[float]:
        return self.__finish_time

    @finish_time.setter
    def finish_time(self, value: typing.Optional[float]) -> None:
        self.__finish_time = value
        self.notify_property_changed("finish_time")
        self.task_changed_event.fire()

    # in progress
    @property
    def in_progress(self) -> bool:
        return self.finish_time is None

    # progress
    @property
    def progress(self) -> typing.Optional[typing.Tuple[int, int]]:
        return self.__progress

    @progress.setter
    def progress(self, value: typing.Optional[typing.Tuple[int, int]]) -> None:
        self.__progress = value
        self.task_changed_event.fire()

    # progress_text
    @property
    def progress_text(self) -> str:
        return self.__progress_text

    @progress_text.setter
    def progress_text(self, value: str) -> None:
        self.__progress_text = value
        self.task_changed_event.fire()

    # task type
    @property
    def task_type(self) -> str:
        return self.__task_type

    # task data
    @property
    def task_data(self) -> typing.Any:
        with self.__task_data_mutex:
            return copy.copy(self.__task_data)

    @task_data.setter
    def task_data(self, task_data: typing.Any) -> None:
        with self.__task_data_mutex:
            self.__task_data = copy.copy(task_data)
        self.notify_property_changed("task_data")
        self.task_changed_event.fire()


# all public methods are thread safe
class TaskContextManager:

    def __init__(self, container: DocumentController.DocumentController, task: Task, logging: bool) -> None:
        self.__container = container
        self.__task = task
        self.__logging = logging

    def __enter__(self) -> TaskContextManager:
        if self.__logging:
            logging.debug("%s: started", self.__task.title)
        self.__task.start_time = time.time()
        return self

    def __exit__(self, exception_type: typing.Optional[typing.Type[BaseException]], value: typing.Optional[BaseException], traceback: typing.Optional[types.TracebackType]) -> typing.Optional[bool]:
        self.__task.finish_time = time.time()
        if self.__logging:
            logging.debug("%s: finished", self.__task.title)
        return None

    def update_progress(self, progress_text: str, progress: typing.Optional[typing.Tuple[int, int]] = None, task_data: typing.Any = None) -> None:
        self.__task.progress_text = progress_text
        self.__task.progress = progress
        if task_data:
            self.__task.task_data = task_data
        if self.__logging:
            logging.debug("%s: %s %s", self.__task.title, progress_text, progress if progress else "")


class TaskController(typing.Protocol):
    widget: UserInterface.Widget

    @property
    def clipboard_text(self) -> str: raise NotImplementedError()

    def update_task(self, task: Task) -> None: ...


class TaskManager(metaclass=Utility.Singleton):

    def __init__(self) -> None:
        self.__task_ui_builder_map: typing.Dict[str, typing.Callable[[UserInterface.UserInterface], TaskController]] = dict()

    def register_task_type_builder(self, task_type: str, fn: typing.Callable[[UserInterface.UserInterface], TaskController]) -> None:
        self.__task_ui_builder_map[task_type] = fn

    def unregister_task_type_builder(self, task_type: str) -> None:
        del self.__task_ui_builder_map[task_type]

    def build_task_ui(self, ui: UserInterface.UserInterface, task: Task) -> typing.Optional[TaskController]:
        if task.task_type in self.__task_ui_builder_map:
            return self.__task_ui_builder_map[task.task_type](ui)
        return None


class TableController(TaskController):

    def __init__(self, ui: UserInterface.UserInterface) -> None:
        self.ui = ui
        self.__clipboard_text = str()
        self.__column_widget = self.ui.create_column_widget()
        self.column_widgets = self.ui.create_row_widget()
        self.__column_widget.add(self.column_widgets)
        self.widget = self.__column_widget

    @property
    def clipboard_text(self) -> str:
        return self.__clipboard_text

    def update_task(self, task: Task) -> None:
        if task.task_data:
            column_count = len(task.task_data["headers"])
            while self.column_widgets.child_count > column_count:
                self.column_widgets.remove(self.column_widgets.child_count - 1)
            while self.column_widgets.child_count < column_count:
                self.column_widgets.add(self.ui.create_column_widget())
            row_count = len(task.task_data["data"]) if "data" in task.task_data else 0
            text_lines: typing.List[typing.List[str]] = [list() for _ in range(row_count + 1)]
            for column_index, column_widget_ in enumerate(self.column_widgets.children):
                column_widget = typing.cast(UserInterface.BoxWidget, column_widget_)
                while column_widget.child_count > row_count + 1:
                    column_widget.remove(column_widget.child_count - 1)
                while column_widget.child_count < row_count + 1:
                    label_widget = self.ui.create_label_widget()
                    if column_widget.child_count == 0:
                        label_widget.text_font = "bold"
                    column_widget.add(label_widget)
                header_text = task.task_data["headers"][column_index]
                typing.cast(UserInterface.LabelWidget, column_widget.children[0]).text = header_text
                text_lines[0].append(header_text)
                for row_index in range(row_count):
                    data_text = str(task.task_data["data"][row_index][column_index])
                    typing.cast(UserInterface.LabelWidget, column_widget.children[row_index + 1]).text = data_text
                    text_lines[row_index + 1].append(data_text)
            self.__clipboard_text = "\n".join(["  ".join(text_line) for text_line in text_lines])
        else:
            self.column_widgets.remove_all()


class StringListController(TaskController):

    def __init__(self, ui: UserInterface.UserInterface) -> None:
        self.ui = ui
        self.__clipboard_text = str()
        self.widget = self.ui.create_label_widget("[]")

    @property
    def clipboard_text(self) -> str:
        return self.__clipboard_text

    def update_task(self, task: Task) -> None:
        strings = task.task_data["strings"] if task.task_data else list()
        self.__clipboard_text = "[" + ":".join(strings) + "]"
        self.widget.text = self.clipboard_text


TaskManager().register_task_type_builder("string_list", lambda ui: StringListController(ui))
TaskManager().register_task_type_builder("table", lambda ui: TableController(ui))
