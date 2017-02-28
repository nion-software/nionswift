# python api_tool.py --classes api_public --level release > ../typeshed/nion/typeshed/API_1_0.py
# python api_tool.py --classes api_public --level release prerelease > ../typeshed/nion/typeshed/API_1_0_prerelease.py
# python api_tool.py --classes hardware_source_public --level release > ../typeshed/nion/typeshed/HardwareSource_1_0.py
# python api_tool.py --classes nionlib_public --level release --proxy > ../PlugIns/Connection/NionLib/nionlib/Classes.py

import argparse
import importlib
import inspect
import typing

parser = argparse.ArgumentParser(description='Generate API type stub files.')
parser.add_argument('--classes', dest='class_list_property', required=True, help='Class list property')
parser.add_argument('--levels', dest='levels', required=True, nargs='+', help='Level property')
parser.add_argument('--proxy', dest='is_proxy', required=False, nargs='?', const=True, default=False, help='Whether to generate proxy function bodies')
parser.add_argument('--summary', dest='is_summary', required=False, nargs='?', const=True, default=False, help='Whether to generate summary text')
args = parser.parse_args()

module = importlib.import_module("nion.swift.Facade")
class_list_property = args.class_list_property
levels = args.levels
is_proxy = args.is_proxy
is_summary = args.is_summary

class_dicts = dict()

# find members of the module which are classes
for member in inspect.getmembers(module, predicate=inspect.isclass):
    class_name = member[0]
    # print("### {}".format(class_name))
    # check to see whether the class_name is in the exported classes (class_list_property)
    if class_name in getattr(module, class_list_property):
        # print("### getattr(module, class_list_property) {}".format(class_name))
        # create a dict to represent this class
        class_dict = dict()
        class_dict["name"] = class_name
        class_dict["doc"] = member[1].__doc__
        # build a list of members that are listed at the appropriate 'level' for export
        members = list()
        for level in levels:
            members.extend(getattr(member[1], level, list()))
        class_dict["threadsafe"] = getattr(member[1], "threadsafe", list())
        # scan through the properties of the class and add their info to the member info
        for member_member in inspect.getmembers(member[1], predicate=lambda x: isinstance(x, property)):
            if member_member[0] in members:
                property_dict = class_dict.setdefault("properties", dict()).setdefault(member_member[0], dict())
                function_get = member_member[1].fget
                if function_get:
                    if function_get.__annotations__:
                        property_dict.setdefault("get", dict())["annotations"] = function_get.__annotations__
                    if function_get.__doc__:
                        property_dict.setdefault("get", dict())["doc"] = function_get.__doc__
                function_set = member_member[1].fset
                if function_set:
                    if function_set.__annotations__:
                        property_dict.setdefault("set", dict())["annotations"] = function_set.__annotations__
                    if function_set.__doc__:
                        property_dict.setdefault("set", dict())["doc"] = function_set.__doc__
        # scan through the functions of the class and add their info to the member info
        for method_member in inspect.getmembers(member[1], predicate=lambda x: inspect.isfunction):
            function_name = method_member[0]
            if function_name in members and function_name not in class_dict.get("properties", dict()):
                function_dict = class_dict.setdefault("functions", dict()).setdefault(function_name, dict())
                function = method_member[1]
                function_dict["fullargspec"] = inspect.getfullargspec(function)
                if function.__doc__:
                    function_dict["doc"] = function.__doc__
        class_dicts[class_name] = class_dict

# pprint.pprint(class_dicts)

def annotation_to_str(annotation):
    if annotation is None:
        return "None"

    annotation_name = getattr(annotation, "__name__", None)

    if type(annotation) == str:
        annotation = getattr(module, annotation)
        return "\"{}\"".format(annotation.__name__)

    if annotation == bool:
        return "bool"
    if annotation == float:
        return "float"
    if annotation == int:
        return "int"
    if annotation == str:
        return "str"
    if annotation == dict:
        return "dict"
    if annotation_name == "Calibration":
        return "Calibration.Calibration"
    if annotation_name == "DataAndMetadata":
        return "DataAndMetadata.DataAndMetadata"
    if annotation_name == "DataDescriptor":
        return "DataAndMetadata.DataDescriptor"
    if annotation_name == "FloatPoint":
        return "Geometry.FloatPoint"

    classes = ["Application", "DataGroup", "DataItem", "Display", "DisplayPanel", "DocumentWindow", "Graphic", "HardwareSource", "Instrument",
        "Library", "RecordTask", "Region", "ViewTask"]

    if annotation_name in classes:
        return annotation_name

    if annotation_name == "ndarray":
        return "numpy.ndarray"
    if annotation_name == typing.List.__name__:
        return "typing.List[{}]".format(annotation_to_str(annotation.__args__[0]))
    if annotation_name == typing.Sequence.__name__:
        return "typing.Sequence[{}]".format(annotation_to_str(annotation.__args__[0]))
    if annotation_name == typing.Tuple.__name__:
        return "typing.Tuple[{}]".format(", ".join(annotation_to_str(tuple_param) for tuple_param in annotation.__args__))
    if annotation_name == "Union":
        return "typing.Union[{}]".format(", ".join(annotation_to_str(union_param) for union_param in annotation.__union_params__))
    if isinstance(annotation, type):
        class_ = annotation.__class__
        if class_ is not None:
            return f"{annotation.__module__}.{annotation.__qualname__}"
        return dir(annotation)
    return str(annotation)

def default_to_str(default):
    return "={}".format(default)


class TypeProducer:
    def reorder_class_names(self, class_names: typing.Sequence[str]) -> typing.Sequence[str]:
        return class_names

    def print_header(self, class_names: typing.Sequence[str]):
        print("import datetime")
        print("import numpy")
        print("import typing")
        print("import uuid")
        print("from nion.data import Calibration")
        print("from nion.data import DataAndMetadata")
        print("from nion.utils import Geometry")

    def print_class(self, class_name: str) -> None:
        print("")
        print("")
        print("class {}:".format(class_name))

    def print_class_doc(self, doc: str) -> None:
        if doc:
            print("    \"\"\"{}\"\"\"".format(doc))

    def print_init(self) -> None:
        pass

    def print_methods_begin(self) -> None:
        pass

    def print_method_def(self, member_name: str, arg_strings: typing.Sequence[str], raw_arg_strings: typing.Sequence[str], return_type: str) -> None:
        print("")
        print("    def {}({}){}:".format(member_name, ", ".join(arg_strings), return_type))

    def print_method_doc(self, doc: str) -> None:
        if doc:
            print("        \"\"\"{}\"\"\"".format(doc))

    def print_method_body(self, member_name: str, arg_str: str, is_threadsafe: bool, is_return_none: bool) -> None:
        print("        ...")

    def print_methods_end(self) -> None:
        pass

    def print_properties_begin(self) -> None:
        pass

    def print_get_property_def(self, property_name: str, property_return_str: str) -> None:
        print("")
        print("    @property")
        print("    def {}(self){}:".format(property_name, property_return_str))

    def print_get_property_doc(self, doc: str) -> None:
        if doc:
            print("        \"\"\"{}\"\"\"".format(doc))

    def print_get_property_body(self, property_name: str) -> None:
        print("        ...")

    def print_set_property_def(self, property_name: str, property_type_str: str) -> None:
        print("")
        print("    @{}.setter".format(property_name))
        print("    def {}(self, value{}) -> None:".format(property_name, property_type_str))

    def print_set_property_doc(self, doc: str) -> None:
        if doc:
            print("        \"\"\"{}\"\"\"".format(doc))

    def print_set_property_body(self, property_name: str) -> None:
        print("        ...")

    def print_properties_end(self) -> None:
        pass

    def print_footer(self):
        print("")
        print("version = \"~1.0\"")


class SummaryProducer:
    def reorder_class_names(self, class_names: typing.Sequence[str]) -> typing.Sequence[str]:
        return sorted(class_names)

    def print_header(self, class_names: typing.Sequence[str]):
        print(".. _api-quick:")
        print("")
        print("API Quick Summary")
        print("=================")
        print("")
        for class_name in class_names:
            print(f"   - {class_name}_")

    def print_class(self, class_name: str) -> None:
        print("")
        print(f".. _{class_name}:")
        print("")
        print(f"{class_name}")
        print("-" * len(class_name))
        print(f"class :py:class:`nion.typeshed.API_1_0.{class_name}`")
        print("")
        self.class_name = class_name

    def print_class_doc(self, doc: str) -> None:
        pass

    def print_init(self) -> None:
        pass

    def print_methods_begin(self) -> None:
        print("**Methods**")

    def print_method_def(self, member_name: str, arg_strings: typing.Sequence[str], raw_arg_strings: typing.Sequence[str], return_type: str) -> None:
        print(f"   - :py:meth:`{member_name} <nion.typeshed.API_1_0.{self.class_name}.{member_name}>`")

    def print_method_doc(self, doc: str) -> None:
        pass

    def print_method_body(self, member_name: str, arg_str: str, is_threadsafe: bool, is_return_none: bool) -> None:
        pass

    def print_methods_end(self) -> None:
        print("")

    def print_properties_begin(self) -> None:
        print("**Properties**")

    def print_get_property_def(self, property_name: str, property_return_str: str) -> None:
        print(f"   - :py:attr:`{property_name} <nion.typeshed.API_1_0.{self.class_name}.{property_name}>`")

    def print_get_property_doc(self, doc: str) -> None:
        pass

    def print_get_property_body(self, property_name: str) -> None:
        pass

    def print_set_property_def(self, property_name: str, property_type_str: str) -> None:
        pass

    def print_set_property_doc(self, doc: str) -> None:
        pass

    def print_set_property_body(self, property_name: str) -> None:
        pass

    def print_properties_end(self) -> None:
        print("")

    def print_footer(self):
        pass


class ProxyProducer:
    def reorder_class_names(self, class_names: typing.Sequence[str]) -> typing.Sequence[str]:
        return class_names

    def print_header(self, class_names: typing.Sequence[str]):
        print("from .Pickler import Unpickler")
        print("")
        print("def call_method(target, method_name, *args, **kwargs):")
        print("    return Unpickler.call_method(target._proxy, target, method_name, *args, **kwargs)")
        print("")
        print("def call_threadsafe_method(target, method_name, *args, **kwargs):")
        print("    return Unpickler.call_threadsafe_method(target._proxy, target, method_name, *args, **kwargs)")
        print("")
        print("def get_property(target, property_name):")
        print("    return Unpickler.get_property(target._proxy, target, property_name)")
        print("")
        print("def set_property(target, property_name, value):")
        print("    return Unpickler.set_property(target._proxy, target, property_name, value)")

    def print_class(self, class_name: str) -> None:
        print("")
        print("")
        print("class {}:".format(class_name))

    def print_class_doc(self, doc: str) -> None:
        pass

    def print_init(self) -> None:
        print("")
        print("    def __init__(self, proxy, specifier):")
        print("        self._proxy = proxy")
        print("        self.specifier = specifier")

    def print_methods_begin(self) -> None:
        pass

    def print_method_def(self, member_name: str, arg_strings: typing.Sequence[str], raw_arg_strings: typing.Sequence[str], return_type: str) -> None:
        print("")
        print("    def {}({}):".format(member_name, ", ".join(raw_arg_strings)))

    def print_method_doc(self, doc: str) -> None:
        pass

    def print_method_body(self, member_name: str, arg_str: str, is_threadsafe: bool, is_return_none: bool) -> None:
        if is_return_none:
            if is_threadsafe:
                print("        call_threadsafe_method(self, '{}'{})".format(member_name, arg_str))
            else:
                print("        call_method(self, '{}'{})".format(member_name, arg_str))
        else:
            if is_threadsafe:
                print("        return call_threadsafe_method(self, '{}'{})".format(member_name, arg_str))
            else:
                print("        return call_method(self, '{}'{})".format(member_name, arg_str))

    def print_methods_end(self) -> None:
        pass

    def print_properties_begin(self) -> None:
        pass

    def print_get_property_def(self, property_name: str, property_return_str: str) -> None:
        print("")
        print("    @property")
        print("    def {}(self):".format(property_name))

    def print_get_property_doc(self, doc: str) -> None:
        pass

    def print_get_property_body(self, property_name: str) -> None:
        print("        return get_property(self, '{}')".format(property_name))

    def print_set_property_def(self, property_name: str, property_type_str: str) -> None:
        print("")
        print("    @{}.setter".format(property_name))
        print("    def {}(self, value):".format(property_name))

    def print_set_property_doc(self, doc: str) -> None:
        pass

    def print_set_property_body(self, property_name: str) -> None:
        print("        set_property(self, '{}', value)".format(property_name))

    def print_properties_end(self) -> None:
        pass

    def print_footer(self):
        pass


if is_proxy:
    producer = ProxyProducer()
elif is_summary:
    producer = SummaryProducer()
else:
    producer = TypeProducer()

class_names = producer.reorder_class_names(getattr(module, class_list_property))

aliased_class_names = list()
for class_name in class_names:
    class_dict = class_dicts[class_name]
    class_name = class_dict["name"]
    class_name = getattr(module, "alias", dict()).get(class_name, class_name)
    aliased_class_names.append(class_name)

producer.print_header(aliased_class_names)

for class_name in class_names:
    class_dict = class_dicts[class_name]
    class_name = class_dict["name"]
    class_name = getattr(module, "alias", dict()).get(class_name, class_name)
    doc = class_dict.get("doc")
    threadsafe = class_dict.get("threadsafe")
    producer.print_class(class_name)
    producer.print_class_doc(doc)
    producer.print_init()
    class_functions_dict = class_dict.get("functions", dict())
    if len(class_functions_dict.keys()) > 0:
        producer.print_methods_begin()
    for member_name in sorted(class_functions_dict.keys()):
        argspec = class_functions_dict[member_name]["fullargspec"]
        # print("    ### {}".format(argspec))
        doc = class_functions_dict[member_name].get("doc")
        raw_arg_strings = list()
        raw_pass_arg_strings = list()
        arg_strings = list()
        for arg in argspec.args:
            annotation = argspec.annotations.get(arg)
            if annotation is not None:
                arg_strings.append("{}: {}".format(arg, annotation_to_str(annotation)))
            else:
                arg_strings.append("{}".format(arg))
            raw_arg_strings.append("{}".format(arg))
            raw_pass_arg_strings.append(f"{arg}")
        default_count = len(argspec.defaults) if argspec.defaults else 0
        for index in range(default_count):
            arg_index = -default_count + index
            default_value_str = default_to_str(argspec.defaults[index])
            arg_strings[arg_index] = "{}{}".format(arg_strings[arg_index], default_value_str)
            raw_arg_strings[arg_index] = f"{raw_arg_strings[arg_index]}{default_value_str}"
            raw_pass_arg_strings[arg_index] = f"{raw_pass_arg_strings[arg_index]}={raw_pass_arg_strings[arg_index]}"
        if len(argspec.kwonlyargs) > 0:
            arg_strings.append("*")
            raw_arg_strings.append("*")
            for kwarg in argspec.kwonlyargs:
                annotation = argspec.annotations.get(kwarg)
                if annotation is not None:
                    arg_string = "{}: {}".format(kwarg, annotation_to_str(annotation))
                else:
                    arg_string = "{}".format(kwarg)
                default_value_str = default_to_str(argspec.kwonlydefaults[kwarg])
                arg_string = "{}{}".format(arg_string, default_value_str)
                arg_strings.append(arg_string)
                raw_arg_strings.append("{}{}".format(kwarg, default_value_str))
                raw_pass_arg_strings.append(f"{kwarg}={kwarg}")
        if "return" in argspec.annotations:
            return_type = " -> {}".format(annotation_to_str(argspec.annotations["return"]))
            is_return_none = argspec.annotations["return"] is None
        else:
            return_type = ""
            is_return_none = False
        arg_str = "".join(", " + raw_arg_string for raw_arg_string in raw_pass_arg_strings[1:])
        is_threadsafe = member_name in threadsafe
        producer.print_method_def(member_name, arg_strings, raw_arg_strings, return_type)
        producer.print_method_doc(doc)
        producer.print_method_body(member_name, arg_str, is_threadsafe, is_return_none)
    if len(class_functions_dict.keys()) > 0:
        producer.print_methods_end()
    class_properties_dict = class_dict.get("properties", dict())
    if len(class_properties_dict.keys()) > 0:
        producer.print_properties_begin()
    for property_name in sorted(class_properties_dict.keys()):
        get_dict = class_properties_dict[property_name].get("get")
        if get_dict:
            property_return_str = str()
            doc = get_dict.get("doc")
            annotations = get_dict.get("annotations", dict())
            if "return" in annotations:
                property_return_str = " -> {}".format(annotation_to_str(annotations["return"]))
            producer.print_get_property_def(property_name, property_return_str)
            producer.print_get_property_doc(doc)
            producer.print_get_property_body(property_name)
        set_dict = class_properties_dict[property_name].get("set")
        if set_dict:
            doc = set_dict.get("doc")
            annotations = set_dict.get("annotations", dict())
            property_type_str = str()
            for k, v in annotations.items():
                if k != "return":
                    property_type_str = ": {}".format(annotation_to_str(v))
            producer.print_set_property_def(property_name, property_type_str)
            producer.print_set_property_doc(doc)
            producer.print_set_property_body(property_name)
    if len(class_properties_dict.keys()) > 0:
        producer.print_properties_end()

producer.print_footer()
