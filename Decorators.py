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
    def __ne__(self, other):
        return self.__object != other()
