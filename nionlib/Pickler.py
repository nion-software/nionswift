import base64
import io
import pickle
import typing
import xmlrpc.client


all_classes = None  # type: typing.List
all_structs = None  # type: typing.List
struct_names = None  # type: typing.Mapping[typing.Any, str]


class Pickler(pickle.Pickler):

    @classmethod
    def pickle(cls, x):
        f = io.BytesIO()
        Pickler(f).dump(x)
        return base64.b64encode(f.getvalue()).decode('utf-8')

    def persistent_id(self, obj: typing.Any):
        for class_ in all_classes:
            if isinstance(obj, class_):
                return class_.__name__, getattr(obj, "specifier")
        for struct in all_structs:
            if isinstance(obj, struct):
                return struct_names.get(struct, struct.__name__), obj.rpc_dict
        return None


class Unpickler(pickle.Unpickler):

    def __init__(self, file, proxy):
        super().__init__(file)
        self.__proxy = proxy

    @classmethod
    def unpickle(cls, proxy, x):
        return cls(io.BytesIO(base64.b64decode(x.encode('utf-8'))), proxy).load()

    @classmethod
    def call_method(cls, proxy, object, method, *args, **kwargs):
        try:
            return Unpickler.unpickle(proxy, proxy.call_method(Pickler.pickle(object), method, Pickler.pickle(args), Pickler.pickle(kwargs)))
        except xmlrpc.client.Fault as e:
            error_type, error_string = e.faultString.split(":", 1)
            if error_type == "<class 'TimeoutError'>":
                raise TimeoutError(error_string) from None
            raise

    @classmethod
    def call_threadsafe_method(cls, proxy, object, method, *args, **kwargs):
        try:
            return Unpickler.unpickle(proxy, proxy.call_threadsafe_method(Pickler.pickle(object), method, Pickler.pickle(args), Pickler.pickle(kwargs)))
        except xmlrpc.client.Fault as e:
            error_type, error_string = e.faultString.split(":", 1)
            if error_type == "<class 'TimeoutError'>":
                raise TimeoutError(error_string) from None
            raise

    @classmethod
    def get_property(cls, proxy, object: typing.Any, name: str) -> typing.Any:
        return Unpickler.unpickle(proxy, proxy.get_property(Pickler.pickle(object), name))

    @classmethod
    def set_property(cls, proxy, object: typing.Any, name: str, value: typing.Any) -> None:
        proxy.set_property(Pickler.pickle(object), name, Pickler.pickle(value))

    def persistent_load(self, pid):
        type_tag, d = pid
        for class_ in all_classes:
            if type_tag == class_.__name__ or type_tag == class_.__name__:
                return class_(self.__proxy, d)
        for struct in all_structs:
            if type_tag == struct_names.get(struct, struct.__name__):
                return struct.from_rpc_dict(d)

        # Always raises an error if you cannot return the correct object.
        # Otherwise, the unpickler will think None is the object referenced
        # by the persistent ID.
        raise pickle.UnpicklingError("unsupported persistent object")
