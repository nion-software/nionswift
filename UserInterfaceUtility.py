# standard libraries
# none

# third party libraries
# none

# local libraries
# none


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


class TupleOneWayToSourceBinding(object):
    def __init__(self, source, attribute, tuple_index):
        self.__source = source
        self.__attribute = attribute
        self.__tuple_index = tuple_index
        self.converter = None
    def __back_converted_value(self, value):
        return self.converter.convert_back(value) if self.converter else value
    def __converted_value(self, value):
        return self.converter.convert(value) if self.converter else value
    def update_source(self, target_value):
        tuple_as_list = list(getattr(self.__source, self.__attribute))
        tuple_as_list[self.__tuple_index] = self.__back_converted_value(target_value)
        setattr(self.__source, self.__attribute, tuple(tuple_as_list))
    def get_target_value(self):
        return self.__converted_value(getattr(self.__source, self.__attribute)[self.__tuple_index])
