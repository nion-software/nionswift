# standard libraries
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
        context = Schema.SimpleEntityContext()
        item = ItemModel.create(context)
        self.assertIsNotNone(item.uuid)
        self.assertIsNotNone(item.modified)
        d = item.write_to_dict()
        self.assertIn("uuid", d)
        self.assertIn("modified", d)

    def test_reference_is_initially_none(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        RefModel = Schema.entity("ref", None, None, {"item": Schema.reference(ItemModel)})
        context = Schema.SimpleEntityContext()
        ref = RefModel.create(context)
        self.assertIsNone(ref._get_field_value("item"))

    def test_setting_reference_works(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        RefModel = Schema.entity("ref", None, None, {"item": Schema.reference(ItemModel)})
        context = Schema.SimpleEntityContext()
        ref = RefModel.create(context)
        item = ItemModel.create(context)
        ref._set_field_value("item", item)
        self.assertEqual(item, ref._get_field_value("item"))
        ref._set_field_value("item", None)
        self.assertIsNone(ref._get_field_value("item"))

    def test_setting_reference_triggers_property_changes_event(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        RefModel = Schema.entity("ref", None, None, {"item": Schema.reference(ItemModel)})
        context = Schema.SimpleEntityContext()
        ref = RefModel.create(context)
        item = ItemModel.create(context)
        changed = False

        def property_changed(name: str) -> None:
            nonlocal changed
            changed = True

        listener = ref.property_changed_event.listen(property_changed)
        ref._set_field_value("item", item)
        self.assertTrue(changed)

    def test_component_container_is_set_when_inserting_item_and_cleared_when_removing(self):
        ItemModel = Schema.entity("item", None, None, {"flag": Schema.prop(Schema.BOOLEAN)})
        ContainerModel = Schema.entity("c", None, None, {
            "c_items": Schema.array(Schema.component(ItemModel)),
            "r_items": Schema.array(Schema.reference(ItemModel)),
            "c_item": Schema.component(ItemModel),
            "r_item": Schema.reference(ItemModel),
        })
        context = Schema.SimpleEntityContext()
        c = ContainerModel.create(context)
        c._append_item("c_items", ItemModel.create(context))
        c._append_item("c_items", ItemModel.create(context))
        c._append_item("r_items", ItemModel.create(context))
        c._append_item("r_items", ItemModel.create(context))
        c._set_field_value("c_item", ItemModel.create(context))
        c._set_field_value("r_item", ItemModel.create(context))
        self.assertEqual(c, c._get_array_item("c_items", 0)._container)
        self.assertEqual(c, c._get_array_item("c_items", 1)._container)
        self.assertIsNone(c._get_array_item("r_items", 0)._container)
        self.assertIsNone(c._get_array_item("r_items", 1)._container)
        self.assertEqual(c, c._get_field_value("c_item")._container)
        self.assertIsNone(c._get_field_value("r_item")._container)
        c_item0 = c._get_array_item("c_items", 0)
        c._remove_item("c_items", c_item0)
        self.assertIsNone(c_item0._container)
        c_item = c._get_field_value("c_item")
        c._set_field_value("c_item", None)
        self.assertIsNone(c_item._container)

    # modified gets updated when setting field or inserting/removing item
    # referenced items write and read
    # reading item uses custom entity class
