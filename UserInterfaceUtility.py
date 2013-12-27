# standard libraries
# none

# third party libraries
# none

# local libraries
from nion.swift import Decorators
from nion.swift import Storage


# format the text of a line edit widget to and from integer value
class IntegerFormatter(object):

    def __init__(self, line_edit):
        self.line_edit = line_edit

    def format(self, text):
        self.value = int(text)

    def __get_value(self):
        return int(self.line_edit.text)
    def __set_value(self, value):
        self.line_edit.text = str(value)
    value = property(__get_value, __set_value)


# format the text of a line edit widget to and from float value
class FloatFormatter(object):

    def __init__(self, line_edit):
        self.line_edit = line_edit

    def format(self, text):
        self.value = float(text)

    def __get_value(self):
        return float(self.line_edit.text)
    def __set_value(self, value):
        self.line_edit.text = "%g" % float(value)
    value = property(__get_value, __set_value)


class FloatToStringConverter(object):
    """
        Converter object to convert from float value to string and back.
        """
    def convert(self, value):
        return "%g" % float(value)
    def convert_back(self, str):
        return float(str)


class PropertyTwoWayBinding(Storage.Observable):

    """
        Binds to a property of a source object. Changes to the source are
        propogated to the target and changes to the target are propogated to the
        source.
    """

    def __init__(self, source, property_name, target_updater, converter=None):
        super(PropertyTwoWayBinding, self).__init__()
        self.__task_set = Decorators.TaskSet()
        self.__source = source
        self.__property_name = property_name
        self.__source.add_observer(self)
        self.__converter = converter
        self.__source.add_observer(self)
        self.__target_updater = target_updater

    # not thread safe
    def close(self):
        self.__source.remove_observer(self)

    # not thread safe
    def periodic(self):
        self.__task_set.perform_tasks()

    # thread safe
    def add_task(self, key, task):
        self.__task_set.add_task(key, task)

    # thread safe
    def __get_source(self):
        return self.__source
    def __set_source(self, source):
        self.__source = source
        self.notify_set_property("source", source)
    source = property(__get_source, __set_source)

    # thread safe
    def property_changed(self, sender, property, value):
        if sender == self.__source and property == self.__property_name:
            # perform on the main thread
            self.add_task("update_target", lambda: self.update_target(value))

    # thread safe
    def __back_converted_value(self, target_value):
        return self.__converter.convert_back(target_value) if self.__converter else target_value

    # thread safe
    def __converted_value(self, source_value):
        return self.__converter.convert(source_value) if self.__converter else source_value

    # thread safe
    def update_source(self, target_value):
        converted_value = self.__back_converted_value(target_value)
        setattr(self.__source, self.__property_name, converted_value)

    # not thread safe
    def update_target(self, source_value):
        converted_value = self.__converted_value(source_value)
        self.__target_updater(converted_value)

    # thread safe
    def get_target_value(self):
        return self.__converted_value(getattr(self.__source, self.__property_name))


class TupleOneWayToSourceBinding(object):

    """
        Binds one way to an item within a tuple specified by the tuple
        index. Changes to the tuple are not propogated to the target since this is
        a one way binding.
    """

    def __init__(self, source, property_name, tuple_index, converter=None):
        self.__source = source
        self.__property_name = property_name
        self.__tuple_index = tuple_index
        self.__converter = converter

    # not thread safe
    def close(self):
        pass

    # not thread safe
    def periodic(self):
        pass

    # thread safe
    def __back_converted_value(self, target_value):
        return self.__converter.convert_back(target_value) if self.__converter else target_value

    # thread safe
    def __converted_value(self, source_value):
        return self.__converter.convert(source_value) if self.__converter else source_value

    # thread safe
    def update_source(self, target_value):
        tuple_as_list = list(getattr(self.__source, self.__property_name))
        tuple_as_list[self.__tuple_index] = self.__back_converted_value(target_value)
        setattr(self.__source, self.__property_name, tuple(tuple_as_list))

    # thread safe
    def get_target_value(self):
        return self.__converted_value(getattr(self.__source, self.__property_name)[self.__tuple_index])
