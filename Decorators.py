# standard libraries
import functools
import logging
import threading
import time
import os

# third party libraries
# None

# local libraries
# None

def singleton(cls):
    instances = {}

    def getinstance():
        if cls not in instances:
            instances[cls] = cls()
        return instances[cls]

    return getinstance


def timeit(method):

    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()

        print '%r %2.2f sec' % (method.__name__, te - ts)
        #print '%r (%r, %r) %2.2f sec' % (method.__name__, args, kw, te - ts)
        return result

    return timed


# classes which use this decorator on a method are required
# to define two properties: main_thread and delay_queue.
# if the method is called on a thread that does not match
# main_thread, the function is queued into the delay_queue.
def ensure_main_thread(f):

    class f_obj(object):
        def __init__(self, f, args, kw):
            self.f = f
            self.args = args
            self.kw = kw
        def execute(self):
            self.f(*self.args, **self.kw)

    def new_function(*args, **kw):
        if True: #threading.current_thread() != args[0].main_thread:
            f_delay = f_obj(f, args, kw)
            args[0].delay_queue.put(f_delay)
        else:
            f(*args, **kw)
    return new_function


# classes which use this decorator on a method are required
# to define a property: delay_queue.
def queue_main_thread(f):
    @functools.wraps(f)
    def new_function(self, *args, **kw):
        # using wraps we still get useful info about the function we're calling
        # eg the name
        wrapped_f = functools.wraps(f)(lambda args=args, kw=kw: f(self, *args, **kw))
        self.delay_queue.put(wrapped_f)
    return new_function


# classes which use this decorator on a method are required
# to define a property: delay_queue. methods wrapped with this
# decorator MUST be called from a thread or else they will hang.
def queue_main_thread_sync(f):
    @functools.wraps(f)
    def new_function(self, *args, **kw):
        # using wraps we still get useful info about the function we're calling
        # eg the name
        e = threading.Event()
        def sync_f(f, event):
            f()
            event.set()
        wrapped_f = functools.wraps(f)(lambda args=args, kw=kw: f(self, *args, **kw))
        synced_f = functools.partial(sync_f, wrapped_f, e)
        self.delay_queue.put(synced_f)
        e.wait()
    return new_function


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
