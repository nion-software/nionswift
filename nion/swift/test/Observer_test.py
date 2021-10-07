# standard libraries
import collections.abc
import contextlib
import copy
import typing
import unittest

# third party libraries

# local libraries
from nion.swift.model import Observer
from nion.utils import StructuredModel


class TestObserver(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_observer_item_property(self):
        # configure the model
        str_field = StructuredModel.define_field("s", StructuredModel.STRING, default="ss")
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).prop("s")
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            self.assertEqual("ss", o.item)
            model.s = "tt"
            self.assertEqual("tt", o.item)

    def test_observer_item_transform(self):
        # configure the model
        str_field = StructuredModel.define_field("s", StructuredModel.STRING, default="ss")
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).prop("s").transform(lambda x: x.upper())
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            self.assertEqual("SS", o.item)
            model.s = "tt"
            self.assertEqual("TT", o.item)

    def test_observer_item_constant(self):
        # configure the model
        str_field = StructuredModel.define_field("s", StructuredModel.STRING, default="ss")
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).prop("s").constant("N/A")
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            self.assertEqual("N/A", o.item)
            model.s = "tt"
            self.assertEqual("N/A", o.item)

    def test_observer_item_tuple(self):
        # configure the model
        str_field = StructuredModel.define_field("s", StructuredModel.STRING, default="ss")
        number_field = StructuredModel.define_field("n", StructuredModel.INT, default=10)
        schema = StructuredModel.define_record("R", [str_field, number_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).tuple(oo.x.prop("s"), oo.x.prop("n"))
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            self.assertEqual(("ss", 10), o.item)
            model.s = "tt"
            self.assertEqual(("tt", 10), o.item)
            model.n = 4
            self.assertEqual(("tt", 4), o.item)

    def test_observer_action(self):
        # configure the model
        str_field = StructuredModel.define_field("s", StructuredModel.STRING, default="ss")
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        value = ""
        class Action(Observer.AbstractAction):
            def __init__(self, item_value):
                nonlocal value
                value = item_value
            def close(self) -> None:
                pass
        oo = Observer.ObserverBuilder()
        oo.source(model).prop("s").action(Action)
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            self.assertEqual("ss", value)
            model.s = "tt"
            self.assertEqual("tt", value)

    def test_observer_item_array(self):
        # configure the model
        array_field = StructuredModel.define_array(StructuredModel.STRING)
        str_field = StructuredModel.define_field("a", array_field, default=["a", "b", "c"])
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).array("a")
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            self.assertEqual(["a", "b", "c"], o.item)
            model.a.insert(1, "a-b")
            self.assertEqual(["a", "a-b", "b", "c"], o.item)
            del model.a[2]
            self.assertEqual(["a", "a-b", "c"], o.item)

    def test_observer_item_array_sequence(self):
        # configure the model
        array_field = StructuredModel.define_array(StructuredModel.STRING)
        str_field = StructuredModel.define_field("a", array_field, default=["a", "b", "c"])
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).sequence_from_array("a")
        with contextlib.closing(typing.cast(Observer.AbstractItemSequenceSource, oo.make_observable())) as o:
            # check the observer functionality
            # items will be unordered
            self.assertEqual(["a", "b", "c"], o.items)
            model.a.insert(1, "a-b")
            self.assertEqual(["a", "b", "c", "a-b"], o.items)
            del model.a[0]
            self.assertEqual(["b", "c", "a-b"], o.items)

    def test_observer_item_sequence_for_each(self):
        # configure the model
        array_field = StructuredModel.define_array(StructuredModel.STRING)
        str_field = StructuredModel.define_field("a", array_field, default=["a", "b", "c"])
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        values = list()
        class Action(Observer.AbstractAction):
            def __init__(self, item_value):
                nonlocal values
                values.append(item_value)
            def close(self) -> None:
                pass
        oo = Observer.ObserverBuilder()
        oo.source(model).sequence_from_array("a").for_each(oo.x.action(Action))
        with contextlib.closing(typing.cast(Observer.AbstractItemSequenceSource, oo.make_observable())) as o:
            # check the observer functionality
            # items will be unordered
            self.assertEqual(["a", "b", "c"], values)
            model.a.insert(1, "a-b")
            self.assertEqual(["a", "b", "c", "a-b"], values)

    def test_observer_item_sequence_map(self):
        # configure the model
        array_field = StructuredModel.define_array(StructuredModel.STRING)
        str_field = StructuredModel.define_field("a", array_field, default=["a", "b", "c"])
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).sequence_from_array("a").map(oo.x.transform(lambda x: x.upper()))
        with contextlib.closing(typing.cast(Observer.AbstractItemSequenceSource, oo.make_observable())) as o:
            # check the observer functionality
            # items will be unordered
            self.assertEqual(["A", "B", "C"], o.items)
            model.a.insert(1, "a-b")
            self.assertEqual(["A", "B", "C", "A-B"], o.items)
            del model.a[0]
            self.assertEqual(["B", "C", "A-B"], o.items)

    def test_observer_item_sequence_filter(self):
        # configure the model
        array_field = StructuredModel.define_array(StructuredModel.STRING)
        str_field = StructuredModel.define_field("a", array_field, default=["a", "b", "c"])
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        predicate = lambda x: not x.startswith("a")
        oo.source(model).ordered_sequence_from_array("a").filter(predicate)
        with contextlib.closing(typing.cast(Observer.AbstractItemSequenceSource, oo.make_observable())) as o:
            # check the observer functionality
            self.assertEqual(["b", "c"], o.items)  # a, b, c
            model.a.insert(1, "a-b")
            self.assertEqual(["b", "c"], o.items)  # a, a-b, b, c
            model.a.insert(0, "b-a")
            self.assertEqual(["b-a", "b", "c"], o.items)  # b-a, a, a-b, b, c
            del model.a[1]
            self.assertEqual(["b-a", "b", "c"], o.items)  # b-a, a-b, b, c
            del model.a[2]
            self.assertEqual(["b-a", "c"], o.items)  # b-a, a-b, c

    def test_observer_item_sequence_collect(self):
        # configure the model
        array_field = StructuredModel.define_array(StructuredModel.STRING)
        str_field = StructuredModel.define_field("a", array_field, default=["a", "b", "c"])
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).sequence_from_array("a").map(oo.x.transform(lambda x: x.upper())).collect_list()
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            # items will be unordered
            self.assertEqual(["A", "B", "C"], o.item)
            model.a.insert(1, "a-b")
            self.assertEqual(["A", "B", "C", "A-B"], o.item)
            del model.a[0]
            self.assertEqual(["B", "C", "A-B"], o.item)

    def test_observer_item_ordered_sequence_collect(self):
        # configure the model
        array_field = StructuredModel.define_array(StructuredModel.STRING)
        str_field = StructuredModel.define_field("a", array_field, default=["a", "b", "c"])
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).ordered_sequence_from_array("a").map(oo.x.transform(lambda x: x.upper())).collect_list()
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            # items will be ordered
            self.assertEqual(["A", "B", "C"], o.item)
            model.a.insert(1, "a-b")
            self.assertEqual(["A", "A-B", "B", "C"], o.item)
            del model.a[0]
            self.assertEqual(["A-B", "B", "C"], o.item)

    def test_observer_item_ordered_sequence_len(self):
        # configure the model
        array_field = StructuredModel.define_array(StructuredModel.STRING)
        str_field = StructuredModel.define_field("a", array_field, default=["a", "b", "c"])
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        length = 0
        def len_changed(new_length: Observer.ItemValue) -> None:
            nonlocal length
            length = new_length
        oo = Observer.ObserverBuilder()
        oo.source(model).ordered_sequence_from_array("a").map(oo.x.transform(lambda x: x.upper())).len().action_fn(len_changed)
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            # items will be ordered
            self.assertEqual(3, length)
            model.a.insert(1, "a-b")
            self.assertEqual(4, length)
            del model.a[0]
            self.assertEqual(3, length)

    def test_observer_item_sequence_index(self):
        # configure the model
        array_field = StructuredModel.define_array(StructuredModel.STRING)
        str_field = StructuredModel.define_field("a", array_field, default=["a", "b", "c"])
        schema = StructuredModel.define_record("R", [str_field])
        model = StructuredModel.build_model(schema)
        # build the observer
        oo = Observer.ObserverBuilder()
        oo.source(model).ordered_sequence_from_array("a").map(oo.x.transform(lambda x: x.upper())).index(0)
        with contextlib.closing(oo.make_observable()) as o:
            # check the observer functionality
            # items will be ordered
            self.assertEqual("A", o.item)
            model.a.insert(1, "a-b")
            self.assertEqual("A", o.item)
            del model.a[0]
            self.assertEqual("A-B", o.item)
