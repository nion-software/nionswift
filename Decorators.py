# standard libraries
import logging
import threading
import time
import os

# third party libraries
# None

# local libraries
# None

# useful imports to copy and past into other files
# from Decorators import singleton
# from Decorators import timeit
from functools import wraps

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
    @wraps(f)
    def new_function(self, *args, **kw):
        # using wraps we still get useful info about the function we're calling
        # eg the name
        to_add=wraps(f)(lambda args=args, kw=kw: f(self, *args, **kw))
        self.delay_queue.put(to_add)
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
