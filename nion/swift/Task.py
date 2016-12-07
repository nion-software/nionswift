# standard libraries
import copy
import gettext
import logging
import threading
import time

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import Utility
from nion.utils import Event
from nion.utils import Observable

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

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, _("Tasks"))

        # thread safe
        def task_created(task):
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
        self.__pending_tasks = list()
        self.__pending_tasks_mutex = threading.RLock()
        self.__task_needs_update = set()
        self.__task_needs_update_mutex = threading.RLock()
        self.__task_section_controller_list = list()
        self.__task_changed_event_listeners = list()

    def close(self):
        self.document_controller.clear_task(str(id(self)))
        # disconnect to the document controller
        self.__task_created_event_listener.close()
        self.__task_created_event_listener = None
        # disconnect from tasks
        for task_changed_event_listener in self.__task_changed_event_listeners:
            task_changed_event_listener.close()
        self.__task_changed_event_listeners = None
        # finish closing
        super().close()

    # not thread safe
    def __perform_tasks(self):
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
            def task_changed():
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
class TaskSectionController(object):

    def __init__(self, ui, task):
        self.ui = ui
        self.task = task

        widget = self.ui.create_column_widget()
        task_header = self.ui.create_row_widget()
        self.title_widget = self.ui.create_label_widget(properties={"stylesheet": "font-weight: bold"})
        task_header.add(self.title_widget)
        task_spacer_row = self.ui.create_row_widget()
        task_spacer_row_col = self.ui.create_column_widget()
        task_spacer_row.add_spacing(20)
        task_spacer_row.add(task_spacer_row_col)
        self.task_progress_row = self.ui.create_row_widget()
        self.task_progress_label = self.ui.create_label_widget()
        self.task_progress_row.add(self.task_progress_label)
        task_time_row = self.ui.create_row_widget()
        self.task_progress_state = self.ui.create_label_widget(properties={"stylesheet": "font: italic"})
        task_time_row.add(self.task_progress_state)
        task_spacer_row_col.add(self.task_progress_row)
        task_spacer_row_col.add(task_time_row)

        # add custom ui, if any
        self.task_ui_controller = TaskManager().build_task_ui(self.ui, task)
        if self.task_ui_controller:
            task_spacer_row_col.add(self.task_ui_controller.widget)

        widget.add(task_header)
        widget.add(task_spacer_row)

        self.__title_text = None
        copy_button = self.ui.create_push_button_widget(_("Copy to Clipboard"))
        def copy_to_clipboard():
            clipboard_text = self.task_ui_controller.clipboard_text
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
    def update(self):

        # update the title
        self.__title_text = str(self.task.title).upper()
        self.title_widget.text = str(self.task.title)

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

    def __init__(self, title, task_type):
        super().__init__()
        self.__title = title
        self.__start_time = None
        self.__finish_time = None
        self.__task_type = task_type
        self.__task_data = None
        self.__task_data_mutex = threading.RLock()
        self.__progress = None
        self.__progress_text = str()
        self.task_changed_event = Event.Event()

    # title
    @property
    def title(self):
        return self.__title

    @title.setter
    def title(self, value):
        self.__title = value
        self.notify_property_changed("title")
        self.task_changed_event.fire()

    # start time
    @property
    def start_time(self):
        return self.__start_time

    @start_time.setter
    def start_time(self, value):
        self.__start_time = value
        self.notify_property_changed("start_time")
        self.task_changed_event.fire()

    # finish time
    @property
    def finish_time(self):
        return self.__finish_time

    @finish_time.setter
    def finish_time(self, value):
        self.__finish_time = value
        self.notify_property_changed("finish_time")
        self.task_changed_event.fire()

    # in progress
    @property
    def in_progress(self):
        return self.finish_time is None

    # progress
    @property
    def progress(self):
        return self.__progress

    @progress.setter
    def progress(self, value):
        self.__progress = value
        self.task_changed_event.fire()

    # progress_text
    @property
    def progress_text(self):
        return self.__progress_text

    @progress_text.setter
    def progress_text(self, value):
        self.__progress_text = value
        self.task_changed_event.fire()

    # task type
    @property
    def task_type(self):
        return self.__task_type

    # task data
    @property
    def task_data(self):
        with self.__task_data_mutex:
            return copy.copy(self.__task_data)

    @task_data.setter
    def task_data(self, task_data):
        with self.__task_data_mutex:
            self.__task_data = copy.copy(task_data)
        self.notify_property_changed("task_data")
        self.task_changed_event.fire()


# all public methods are thread safe
class TaskContextManager(object):

    def __init__(self, container, task, logging):
        self.__container = container
        self.__task = task
        self.__logging = logging

    def __enter__(self):
        if self.__logging:
            logging.debug("%s: started", self.__task.title)
        self.__task.start_time = time.time()
        return self

    def __exit__(self, type, value, traceback):
        self.__task.finish_time = time.time()
        if self.__logging:
            logging.debug("%s: finished", self.__task.title)

    def update_progress(self, progress_text, progress=None, task_data=None):
        self.__task.progress_text = progress_text
        self.__task.progress = progress
        if task_data:
            self.__task.task_data = task_data
        if self.__logging:
            logging.debug("%s: %s %s", self.__task.title, progress_text, progress if progress else "")


class TaskManager(metaclass=Utility.Singleton):

    def __init__(self):
        self.__task_ui_builder_map = dict()

    def register_task_type_builder(self, task_type, fn):
        self.__task_ui_builder_map[task_type] = fn

    def unregister_task_type_builder(self, task_type):
        del self.__task_ui_builder_map[task_type]

    def build_task_ui(self, ui, task):
        if task.task_type in self.__task_ui_builder_map:
            return self.__task_ui_builder_map[task.task_type](ui)
        return None


class TableController(object):

    def __init__(self, ui):
        self.ui = ui
        self.clipboard_text = None
        self.widget = self.ui.create_column_widget()
        self.column_widgets = self.ui.create_row_widget()
        self.widget.add(self.column_widgets)

    def update_task(self, task):
        if task.task_data:
            column_count = len(task.task_data["headers"])
            while self.column_widgets.child_count > column_count:
                self.column_widgets.remove(self.column_widgets.child_count - 1)
            while self.column_widgets.child_count < column_count:
                self.column_widgets.add(self.ui.create_column_widget())
            row_count = len(task.task_data["data"]) if "data" in task.task_data else 0
            text_lines = [list() for _ in range(row_count + 1)]
            for column_index, column_widget in enumerate(self.column_widgets.children):
                while column_widget.child_count > row_count + 1:
                    column_widget.remove(column_widget.child_count - 1)
                while column_widget.child_count < row_count + 1:
                    properties = {"stylesheet": "font-weight: bold"} if column_widget.child_count == 0 else None
                    column_widget.add(self.ui.create_label_widget(properties=properties))
                header_text = task.task_data["headers"][column_index]
                column_widget.children[0].text = header_text
                text_lines[0].append(header_text)
                for row_index in range(row_count):
                    data_text = str(task.task_data["data"][row_index][column_index])
                    column_widget.children[row_index + 1].text = data_text
                    text_lines[row_index + 1].append(data_text)
            self.clipboard_text = "\n".join(["  ".join(text_line) for text_line in text_lines])
        else:
            self.column_widgets.remove_all()


class StringListController(object):

    def __init__(self, ui):
        self.ui = ui
        self.widget = self.ui.create_label_widget("[]")
        self.clipboard_text = None

    def update_task(self, task):
        strings = task.task_data["strings"] if task.task_data else list()
        self.clipboard_text = "[" + ":".join(strings) + "]"
        self.widget.text = self.clipboard_text

TaskManager().register_task_type_builder("string_list", lambda ui: StringListController(ui))
TaskManager().register_task_type_builder("table", lambda ui: TableController(ui))
