# futures
from __future__ import absolute_import

# standard libraries
import threading
import time
import os

# third party libraries
# None

# local libraries
# None


def timeit(method):

    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()

        print('%r %2.2f sec' % (method.__name__, te - ts))
        #print('%r (%r, %r) %2.2f sec' % (method.__name__, args, kw, te - ts))
        return result

    return timed


def traceit(method):
    def traced(*args, **kw):
        print('ENTER %r (%r, %r) %s' % (method.__name__, args, kw, threading.current_thread().getName()))
        result = method(*args, **kw)
        print('EXIT %r (%r, %r) %s' % (method.__name__, args, kw, threading.current_thread().getName()))
        return result
    return traced


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
