# standard libraries
import copy
import functools
import logging
import Queue
import threading
import time
import os

# third party libraries
# None

# local libraries
# None


class Singleton(type):
    def __init__(cls, name, bases, dict):
        super(Singleton, cls).__init__(name, bases, dict)
        cls.instance = None

    def __call__(cls,*args,**kw):
        if cls.instance is None:
            cls.instance = super(Singleton, cls).__call__(*args, **kw)
        return cls.instance


def timeit(method):

    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()

        print '%r %2.2f sec' % (method.__name__, te - ts)
        #print '%r (%r, %r) %2.2f sec' % (method.__name__, args, kw, te - ts)
        return result

    return timed


def traceit(method):
    def traced(*args, **kw):
        print 'ENTER %r (%r, %r) %s' % (method.__name__, args, kw, threading.current_thread().getName())
        result = method(*args, **kw)
        print 'EXIT %r (%r, %r) %s' % (method.__name__, args, kw, threading.current_thread().getName())
        return result
    return traced


require_main_thread = True


# classes which use this decorator on a method are required
# to define a property: delay_queue.
def queue_main_thread(f):
    @functools.wraps(f)
    def new_function(self, *args, **kw):
        if require_main_thread:
            # using wraps we still get useful info about the function we're calling
            # eg the name
            wrapped_f = functools.wraps(f)(lambda args=args, kw=kw: f(self, *args, **kw))
            self.delay_queue.queue_main_thread_task(wrapped_f)
        else:
            f(self, *args, **kw)
    return new_function


# classes which use this decorator on a method are required
# to define a property: delay_queue.
def queue_main_thread_sync(f):
    @functools.wraps(f)
    def new_function(self, *args, **kw):
        if require_main_thread:
            # using wraps we still get useful info about the function we're calling
            # eg the name
            e = threading.Event()
            def sync_f(f, event):
                try:
                    f()
                finally:
                    event.set()
            wrapped_f = functools.wraps(f)(lambda args=args, kw=kw: f(self, *args, **kw))
            synced_f = functools.partial(sync_f, wrapped_f, e)
            self.delay_queue.queue_main_thread_task(synced_f)
            # how do we tell if this is the main (presumably UI) thread?
            # the order from threading.enumerate() is not reliable
            if threading.current_thread().getName() != "MainThread":
                if not e.wait(5):
                    logging.debug("TIMEOUT %s", f)
        else:
            f(self, *args, **kw)
    return new_function


class TaskQueue(Queue.Queue):
    def perform_tasks(self):
        # perform any pending operations
        qsize = self.qsize()
        while not self.empty() and qsize > 0:
            try:
                task = self.get(False)
            except Queue.Empty:
                pass
            else:
                task()
                self.task_done()
            qsize -= 1


# keeps a set of tasks to do when perform_tasks is called.
# each task is associated with a key. overwriting a key
# will discard any task currently associated with that key.
class TaskSet(object):
    def __init__(self):
        self.__task_dict = dict()
        self.__task_dict_mutex = threading.RLock()
    def add_task(self, key, task):
        with self.__task_dict_mutex:
            self.__task_dict[key] = task
    def perform_tasks(self):
        with self.__task_dict_mutex:
            task_dict = copy.copy(self.__task_dict)
            self.__task_dict.clear()
        for task in task_dict.values():
            task()


def relative_file(parent_path, filename):
    # nb os.path.abspath is os.path.realpath
    dir = os.path.dirname(os.path.abspath(parent_path))
    return os.path.join(dir, filename)


# experimental class to ref count objects. similar to weakref.
# calls about_to_delete when ref count goes to zero.
class countedref(object):
    objects = {}
    def __init__(self, object):
        self.__object = object
        if self.__object:
            if object in countedref.objects:
                countedref.objects[object] += 1
            else:
                countedref.objects[object] = 1
    def __del__(self):
        if self.__object:
            assert self.__object in countedref.objects
            countedref.objects[self.__object] -= 1
            if countedref.objects[self.__object] == 0:
                del countedref.objects[self.__object]
                self.__object.about_to_delete()
    def __call__(self):
        return self.__object
    def __eq__(self, other):
        return self.__object == other()


# calculates the histogram data and the associated javascript to display
class ProcessingThread(object):

    def __init__(self, minimum_interval=None):
        self.__thread_break = False
        self.__thread_ended_event = threading.Event()
        self.__thread_event = threading.Event()
        self.__thread_lock = threading.Lock()
        self.__thread = threading.Thread(target=self.__process)
        self.__thread.daemon = True
        self.__minimum_interval = minimum_interval
        self.__last_time = 0

    def start(self):
        self.__thread.start()

    def close(self):
        with self.__thread_lock:
            self.__thread_break = True
            self.__thread_event.set()
        self.__thread_ended_event.wait()

    def update_data(self, *args, **kwargs):
        with self.__thread_lock:
            self.handle_data(*args, **kwargs)
            self.__thread_event.set()

    def handle_data(self, data_item):
        raise NotImplementedError()

    def grab_data(self):
        raise NotImplementedError()

    def process_data(self, data):
        raise NotImplementedError()

    def release_data(self, data):
        raise NotImplementedError()

    def __process(self):
        while True:
            self.__thread_event.wait()
            with self.__thread_lock:
                self.__thread_event.clear()  # put this inside lock to avoid race condition
                data = self.grab_data()
            if self.__thread_break:
                if data is not None:
                    self.release_data(data)
                break
            thread_event_set = False
            while not self.__thread_break:
                elapsed = time.time() - self.__last_time
                if self.__minimum_interval and elapsed < self.__minimum_interval:
                    if self.__thread_event.wait(self.__minimum_interval - elapsed):
                        thread_event_set = True  # set this so that we know to set it after this loop
                    self.__thread_event.clear()  # clear this so that it doesn't immediately trigger again
                else:
                    break
            if thread_event_set:
                self.__thread_event.set()
            if self.__thread_break:
                if data is not None:
                    self.release_data(data)
                break
            try:
                self.process_data(data)
            except Exception as e:
                import traceback
                logging.debug("Processing thread exception %s", e)
                traceback.print_exc()
            finally:
                if data is not None:
                    self.release_data(data)
            self.__last_time = time.time()
        self.__thread_ended_event.set()
