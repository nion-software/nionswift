# standard libraries
import gettext
import logging
import threading
import time

# third party libraries
# None

# local libraries
from nion.swift.Decorators import singleton
from nion.swift import Panel
from nion.swift import Storage

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
        super(TaskPanel, self).__init__(document_controller, panel_id, _("Tasks"))

        # connect to the document controller
        self.document_controller.add_listener(self)

        # the main column widget contains a stack group for each operation
        self.column = self.ui.create_column_widget(properties)  # TODO: put this in scroll area
        self.scroll_area = self.ui.create_scroll_area_widget()
        self.scroll_area.set_scrollbar_policies("off", "needed")
        self.task_column_container = self.ui.create_column_widget()
        self.task_column = self.ui.create_column_widget()
        self.task_column_container.add(self.task_column)
        self.task_column_container.add_stretch()
        self.scroll_area.content = self.task_column_container
        self.column.add(self.scroll_area)
        self.widget = self.column

        # map task (uuid) to widgets
        self.__pending_tasks = list()
        self.__pending_tasks_mutex = threading.RLock()
        self.__task_map = dict()

    def add_task_section(self, title):
        task_section = self.ui.create_column_widget()
        task_header = self.ui.create_row_widget()
        task_header.add(self.ui.create_label_widget())
        task_progress_row = self.ui.create_row_widget()
        task_progress_row.add(self.ui.create_label_widget())
        task_time_row = self.ui.create_row_widget()
        task_time_row.add(self.ui.create_label_widget())
        task_section.add(task_header)
        task_section.add(task_progress_row)
        task_section.add(task_time_row)
        self.task_column.insert(task_section, 0)
        self.scroll_area.scroll_to(0, 0)
        return task_section

    def close(self):
        # disconnect to the document controller
        self.document_controller.remove_listener(self)
        # finish closing
        super(TaskPanel, self).close()

    def periodic(self):
        with self.__pending_tasks_mutex:
            pending_tasks = self.__pending_tasks
            self.__pending_tasks = list()
        for task in pending_tasks:
            task_section = self.add_task_section(task.title)
            self.__task_map[task.uuid] = task_section

    # may be called on a thread
    def task_created(self, task):
        with self.__pending_tasks_mutex:
            self.__pending_tasks.append(task)

    # only called on UI thread
    def task_updated(self, task):
        if task.uuid in self.__task_map:
            task_section = self.__task_map[task.uuid]
            task_section.children[1].children[0].text = "{} {}".format(task.progress_text, task.progress)
            task_section.children[2].children[0].text = "{}".format(time.strftime("%c", time.gmtime(task.finish_time if task.finish_time else task.start_time)))


class Task(Storage.StorageBase):

    def __init__(self, title, task_type, task_data=None, start_time=None, finish_time=None):
        super(Task, self).__init__()
        self.storage_properties += ["title", "task_type", "task_data", "start_time", "finish_time"]
        self.storage_type = "task"
        self.__title = title
        self.__start_time = None
        self.__finish_time = None
        self.__task_type = task_type
        self.__task_data = None
        self.__task_data_mutex = threading.RLock()

    @classmethod
    def build(cls, storage_reader, item_node, uuid_):
        title = storage_reader.get_property(item_node, "title", None)
        task_type = storage_reader.get_property(item_node, "task_type", None)
        task_data = storage_reader.get_property(item_node, "task_data", None)
        start_time = storage_reader.get_property(item_node, "start_time", None)
        finish_time = storage_reader.get_property(item_node, "finish_time", None)
        return cls(title, task_type, task_data=task_datam, start_time=start_time, finish_time=finish_time)

    def __deepcopy__(self, memo):
        task = Task(self.task_type, self.task_data)
        memo[id(self)] = task
        return task

    # title
    def __get_title(self):
        return self.__title
    def __set_title(self, value):
        self.__title = value
        self.notify_set_property("title", value)
    title = property(__get_title, __set_title)

    # start time
    def __get_start_time(self):
        return self.__start_time
    def __set_start_time(self, value):
        self.__start_time = value
        self.notify_set_property("start_time", value)
    start_time = property(__get_start_time, __set_start_time)

    # finish time
    def __get_finish_time(self):
        return self.__finish_time
    def __set_finish_time(self, value):
        self.__finish_time = value
        self.notify_set_property("finish_time", value)
    finish_time = property(__get_finish_time, __set_finish_time)

    # task type
    def __get_task_type(self):
        return self.__task_type
    task_type = property(__get_task_type)

    # task data
    def __get_task_data(self):
        with self.__task_data_mutex:
            return copy.copy(self.__task_data)
    def __set_task_data(self, task_data):
        with self.__task_data_mutex:
            self.__task_data = copy.copy(task_data)
        self.notify_set_property("origin", value)
    task_data = property(__get_task_data, __set_task_data)


# all public methods are thread safe
class TaskController(object):

    def __init__(self, container, task):
        self.__container = container
        self.__task = task

    def __enter__(self):
        logging.debug("%s: started", self.__task.title)
        self.__task.start_time = time.time()
        self.__container.task_started(self)
        return self

    def __exit__(self, type, value, traceback):
        self.__container.task_finished(self)
        self.__task.finish_time = time.time()
        logging.debug("%s: finished", self.__task.title)

    def update_progress(self, progress_text, progress, task_data=None):
        self.__task.progress_text = progress_text
        self.__task.progress = progress
        if task_data:
            self.__task.task_data = task_data
        self.__task_updated = True
        logging.debug("%s: %s %s", self.__task.title, progress_text, progress)

    # this is guaranteed to be called on the UI thread
    def _periodic(self):
        if self.__task_updated:
            self.__container.update_task(self.__task)
            self.__task_updated = False


@singleton
class TaskManager(object):

    def __init__(self):
        pass
