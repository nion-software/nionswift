# standard libraries
import contextlib
import copy
import unittest

# third party libraries

# local libraries
from nion.swift.model import Schema


class TestSchemaClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_new_entity_has_uuid_and_dates(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        try:
            item = ItemModel.create()
            self.assertIsNotNone(item.uuid)
            self.assertIsNotNone(item.modified)
            d = item.write_to_dict()
            self.assertIn("uuid", d)
            self.assertIn("modified", d)
        finally:
            Schema.unregister_entity_type("item")

    def test_entity_updates_modified_and_parent_when_property_changes(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        try:
            item = ItemModel.create()
            self.assertIsNotNone(item.uuid)
            self.assertIsNotNone(item.modified)
            d = item.write_to_dict()
            self.assertIn("uuid", d)
            self.assertIn("modified", d)
            m = item.modified
            item._set_field_value("flag", False)
            item._set_field_value("flag", True)
            self.assertLess(m, item.modified)
        finally:
            Schema.unregister_entity_type("item")

    def test_reference_is_initially_none(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        RefModel = Schema.entity("ref", None, None, {"item": Schema.reference(ItemModel)})
        try:
            ref = RefModel.create(Schema.SimpleEntityContext())
            self.assertIsNone(ref._get_field_value("item"))
        finally:
            Schema.unregister_entity_type("item")
            Schema.unregister_entity_type("ref")

    def test_setting_reference_works(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        RefModel = Schema.entity("ref", None, None, {"item": Schema.reference(ItemModel)})
        try:
            context = Schema.SimpleEntityContext()
            ref = RefModel.create(context)
            item = ItemModel.create()
            ref._set_field_value("item", item)
            self.assertEqual(item, ref._get_field_value("item"))  # check that the field value was set
            self.assertIsNone(item._entity_context)  # setting a reference should NOT propagate the context
            ref._set_field_value("item", None)
            self.assertIsNone(ref._get_field_value("item"))
            self.assertIsNone(item._entity_context)  # context should be unset now
        finally:
            Schema.unregister_entity_type("item")
            Schema.unregister_entity_type("ref")

    def test_setting_reference_before_context_works(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        RefModel = Schema.entity("ref", None, None, {"item": Schema.reference(ItemModel)})
        try:
            context = Schema.SimpleEntityContext()
            ref = RefModel.create()
            item = ItemModel.create()
            ref._set_field_value("item", item)
            self.assertEqual(item, ref._get_field_value("item"))  # check that the field value was set
            self.assertIsNone(item._entity_context)  # setting the item should propagate the context
            ref._set_entity_context(context)
            self.assertEqual(item, ref._get_field_value("item"))  # check that the field value was set
            self.assertIsNone(item._entity_context)  # setting a reference item should NOT propagate the context
            ref._set_entity_context(None)
            self.assertEqual(item, ref._get_field_value("item"))  # check that the field value was set
            self.assertIsNone(item._entity_context)  # setting the item should propagate the context
            ref._set_field_value("item", None)
            self.assertIsNone(ref._get_field_value("item"))
            self.assertIsNone(item._entity_context)  # context should be unset now
        finally:
            Schema.unregister_entity_type("item")
            Schema.unregister_entity_type("ref")

    def test_setting_reference_triggers_property_changes_event(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        RefModel = Schema.entity("ref", None, None, {"item": Schema.reference(ItemModel)})
        try:
            context = Schema.SimpleEntityContext()
            ref = RefModel.create(context)
            item = ItemModel.create()
            changed = False

            def property_changed(name: str) -> None:
                nonlocal changed
                changed = True

            with contextlib.closing(ref.property_changed_event.listen(property_changed)) as listener:
                ref._set_field_value("item", item)
                self.assertTrue(changed)
        finally:
            Schema.unregister_entity_type("item")
            Schema.unregister_entity_type("ref")

    def test_inserting_and_removing_array_components_and_references_updates_contexts(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        ContainerModel = Schema.entity("c", None, None, {
            "c_items": Schema.array(Schema.component(ItemModel)),
            "r_items": Schema.array(Schema.reference(ItemModel)),
        })
        try:
            context = Schema.SimpleEntityContext()
            c = ContainerModel.create(context)
            # test component
            c_item = ItemModel.create()
            c._append_item("c_items", c_item)
            self.assertIsNotNone(c_item._entity_context)
            c._remove_item("c_items", c_item)
            self.assertIsNone(c_item._entity_context)
            # test reference
            c._append_item("r_items", c_item)
            r_item = c._get_array_item("r_items", 0)
            self.assertIsNone(r_item._entity_context)  # setting a reference should NOT propagate context
            c._remove_item("r_items", c_item)
            self.assertIsNone(r_item._entity_context)
        finally:
            Schema.unregister_entity_type("item")
            Schema.unregister_entity_type("c")

    def test_inserting_and_removing_array_components_and_references_trigger_events(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        ContainerModel = Schema.entity("c", None, None, {
            "c_items": Schema.array(Schema.component(ItemModel)),
            "r_items": Schema.array(Schema.reference(ItemModel)),
        })
        try:
            context = Schema.SimpleEntityContext()
            c = ContainerModel.create(context)

            inserted_count = 0
            removed_count = 0

            def item_inserted(key: str, value, index: int) -> None:
                nonlocal inserted_count
                inserted_count += 1

            def item_removed(key: str, value, index: int) -> None:
                nonlocal removed_count
                removed_count += 1

            with contextlib.closing(c.item_inserted_event.listen(item_inserted)):
                with contextlib.closing(c.item_removed_event.listen(item_removed)):
                    # test components
                    c._append_item("c_items", ItemModel.create())
                    c._append_item("c_items", ItemModel.create())
                    self.assertEqual(2, inserted_count)
                    self.assertEqual(0, removed_count)
                    c._remove_item("c_items", c._get_array_item("c_items", 0))
                    self.assertEqual(2, inserted_count)
                    self.assertEqual(1, removed_count)
                    # test references
                    c._append_item("r_items", ItemModel.create())
                    c._append_item("r_items", ItemModel.create())
                    self.assertEqual(4, inserted_count)
                    self.assertEqual(1, removed_count)
                    c._remove_item("r_items", c._get_array_item("r_items", 0))
                    self.assertEqual(4, inserted_count)
                    self.assertEqual(2, removed_count)
        finally:
            Schema.unregister_entity_type("item")
            Schema.unregister_entity_type("c")

    def test_component_container_is_set_when_inserting_item_and_cleared_when_removing(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        ContainerModel = Schema.entity("c", None, None, {
            "c_items": Schema.array(Schema.component(ItemModel)),
            "r_items": Schema.array(Schema.reference(ItemModel)),
            "c_item": Schema.component(ItemModel),
            "r_item": Schema.reference(ItemModel),
        })
        try:
            context = Schema.SimpleEntityContext()
            c = ContainerModel.create(context)
            c._append_item("c_items", ItemModel.create())
            c._append_item("c_items", ItemModel.create())
            c._append_item("r_items", c._get_array_item("c_items", 0))
            c._append_item("r_items", c._get_array_item("c_items", 1))
            c._set_field_value("c_item", ItemModel.create())
            c._set_field_value("r_item", c.c_item)
            self.assertEqual(c, c._get_array_item("c_items", 0)._container)
            self.assertEqual(c, c._get_array_item("c_items", 1)._container)
            self.assertEqual(c, c._get_array_item("r_items", 0)._container)
            self.assertEqual(c, c._get_array_item("r_items", 1)._container)
            self.assertEqual(c, c._get_field_value("c_item")._container)
            self.assertEqual(c, c._get_field_value("r_item")._container)
            c_item0 = c._get_array_item("c_items", 0)
            c._remove_item("c_items", c_item0)
            self.assertIsNone(c_item0._container)
            c_item = c._get_field_value("c_item")
            c._set_field_value("c_item", None)
            self.assertIsNone(c_item._container)
        finally:
            Schema.unregister_entity_type("item")
            Schema.unregister_entity_type("c")

    def test_deepcopy(self):
        RecordModel = Schema.record({
            "value": Schema.prop(Schema.INT),
        })
        ItemModel = Schema.entity("item", None, None, {
            "name": Schema.prop(Schema.STRING),
            "record": RecordModel,
        })
        ListModel = Schema.entity("list", None, None, {
            "c_items": Schema.array(Schema.component(ItemModel)),
            "r_items": Schema.array(Schema.reference(ItemModel)),
        })
        try:
            context = Schema.SimpleEntityContext()
            with contextlib.closing(ListModel.create(context)) as l:
                l._append_item("c_items", ItemModel.create(None, {"name": "aa", "record": {"value": 4}}))
                l._append_item("c_items", ItemModel.create(None, {"name": "bb", "record": {"value": 5}}))
                l._append_item("r_items", l._get_array_item("c_items", 0))
                l._append_item("r_items", l._get_array_item("c_items", 1))
                self.assertEqual(4, l._get_array_item("c_items", 0).record.value)
                self.assertEqual(5, l._get_array_item("c_items", 1).record.value)
                self.assertEqual(l._get_array_item("r_items", 0), l._get_array_item("c_items", 0))
                self.assertEqual(l._get_array_item("r_items", 1), l._get_array_item("c_items", 1))
                with contextlib.closing(copy.deepcopy(l)) as ll:
                    self.assertEqual(l._get_array_item("c_items", 0).uuid, ll._get_array_item("c_items", 0).uuid)
                    self.assertEqual(l._get_array_item("c_items", 1).uuid, ll._get_array_item("c_items", 1).uuid)
                    self.assertEqual(l._get_array_item("c_items", 0).modified, ll._get_array_item("c_items", 0).modified)
                    self.assertEqual(l._get_array_item("c_items", 1).modified, ll._get_array_item("c_items", 1).modified)
                    self.assertEqual(l._get_array_item("c_items", 0).name, ll._get_array_item("c_items", 0).name)
                    self.assertEqual(l._get_array_item("c_items", 1).name, ll._get_array_item("c_items", 1).name)
                    self.assertEqual(4, ll._get_array_item("c_items", 0).record.value)
                    self.assertEqual(5, ll._get_array_item("c_items", 1).record.value)
                    self.assertEqual(ll._get_array_item("r_items", 0), ll._get_array_item("c_items", 0))
                    self.assertEqual(ll._get_array_item("r_items", 1), ll._get_array_item("c_items", 1))
        finally:
            Schema.unregister_entity_type("item")
            Schema.unregister_entity_type("list")

    def test_non_required_subclass_survives_read_write(self):
        ItemModel = Schema.entity("item", None, None, {
            "name": Schema.prop(Schema.STRING),
        })
        ItemModel1 = Schema.entity("item1", ItemModel, None, {
            "one": Schema.prop(Schema.STRING),
        })
        ItemModel2 = Schema.entity("item2", ItemModel, None, {
            "two": Schema.prop(Schema.STRING),
        })
        ListModel = Schema.entity("list", None, None, {
            "items": Schema.array(Schema.component(ItemModel, False)),
        })
        try:
            context = Schema.SimpleEntityContext()
            with contextlib.closing(ListModel.create(context)) as l:
                l._append_item("items", ItemModel1.create(None, {"name": "1", "one": "11"}))
                l._append_item("items", ItemModel2.create(None, {"name": "2", "two": "22"}))
                d = l.write()
                self.assertEqual("1", l._get_array_item("items", 0).name)
                self.assertEqual("11", l._get_array_item("items", 0).one)
                self.assertEqual("2", l._get_array_item("items", 1).name)
                self.assertEqual("22", l._get_array_item("items", 1).two)
            Schema.unregister_entity_type("item1")
            with contextlib.closing(ListModel.create(context)) as l:
                l.read(d)
                self.assertEqual(d, l.write())
                self.assertIsNone(l._get_array_item("items", 0))
                self.assertEqual("2", l._get_array_item("items", 1).name)
                self.assertEqual("22", l._get_array_item("items", 1).two)
            # re-register and make sure it loads
            Schema.register_entity_type("item1", ItemModel1)
            with contextlib.closing(ListModel.create(context)) as l:
                l.read(d)
                self.assertEqual(d, l.write())
                self.assertEqual("1", l._get_array_item("items", 0).name)
                self.assertEqual("11", l._get_array_item("items", 0).one)
                self.assertEqual("2", l._get_array_item("items", 1).name)
                self.assertEqual("22", l._get_array_item("items", 1).two)
        finally:
            Schema.unregister_entity_type("item")
            Schema.unregister_entity_type("item1")
            Schema.unregister_entity_type("item2")
            Schema.unregister_entity_type("list")

    # test adding values to an array of strings
    # modified gets updated when setting field or inserting/removing item
    # referenced items write and read
    # reading item uses custom entity class
    # context gets set/cleared on proxy when it becomes available/unavailable
