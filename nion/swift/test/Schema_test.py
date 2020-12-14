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

    # referenced items write and read
    # reading item uses custom entity class
