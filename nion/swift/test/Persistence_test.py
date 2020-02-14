# standard libraries
import contextlib
import unittest

# third party libraries
# None

# local libraries
from nion.swift.model import Persistence


class TestPersistentObjectContextClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_persistent_object_context_does_not_trigger_event_on_already_registered_object(self):
        persistent_object_context = Persistence.PersistentObjectContext()
        object1 = Persistence.PersistentObject()
        persistent_object_context.register(object1, object1.item_specifier)
        was_registered = False
        def registered(registered_item, unregistered_item) -> None:
            nonlocal was_registered
            if registered_item:
                was_registered = True
        with persistent_object_context.registration_event.listen(registered):
            self.assertFalse(was_registered)

    def test_persistent_object_context_calls_register_when_object_becomes_registered(self):
        persistent_object_context = Persistence.PersistentObjectContext()
        object1 = Persistence.PersistentObject()
        was_registered = False
        def registered(registered_item, unregistered_item) -> None:
            nonlocal was_registered
            if registered_item == object1:
                was_registered = True
        with persistent_object_context.registration_event.listen(registered):
            persistent_object_context.register(object1, object1.item_specifier)
            self.assertTrue(was_registered)

    def test_persistent_object_context_calls_unregister_when_object_becomes_unregistered(self):
        persistent_object_context = Persistence.PersistentObjectContext()
        object1 = Persistence.PersistentObject()
        was_registered = False
        def registered(registered_item, unregistered_item) -> None:
            nonlocal was_registered
            if registered_item == object1:
                was_registered = True
            if unregistered_item == object1:
                was_registered = False
        with persistent_object_context.registration_event.listen(registered):
            item_specifier1 = object1.item_specifier
            persistent_object_context.register(object1, item_specifier1)
            self.assertTrue(was_registered)
            persistent_object_context.unregister(object1, item_specifier1)
            self.assertFalse(was_registered)

    def test_persistent_object_context_unregister_without_subscription_works(self):
        # this test will only generate extra output in the failure case, which has been fixed
        persistent_object_context = Persistence.PersistentObjectContext()
        object1 = Persistence.PersistentObject()
        persistent_object_context.register(object1, object1.item_specifier)
        object1 = None

    def test_persistent_object_proxy_updates_when_registered(self):
        persistent_object_context = Persistence.PersistentObjectContext()
        object0 = Persistence.PersistentObject()
        object1 = Persistence.PersistentObject()
        object1_proxy = object0.create_item_proxy(item_specifier=Persistence.PersistentObjectSpecifier.read(object1.uuid))
        with contextlib.closing(object1_proxy):
            object0.persistent_object_context = persistent_object_context
            self.assertIsNone(object1_proxy.item)
            object1.persistent_object_context = persistent_object_context
            self.assertEqual(object1, object1_proxy.item)

    def test_persistent_object_proxy_updates_when_unregistered(self):
        persistent_object_context = Persistence.PersistentObjectContext()
        object0 = Persistence.PersistentObject()
        object1 = Persistence.PersistentObject()
        object1_proxy = object0.create_item_proxy(item_specifier=Persistence.PersistentObjectSpecifier.read(object1.uuid))
        with contextlib.closing(object1_proxy):
            object0.persistent_object_context = persistent_object_context
            object1.persistent_object_context = persistent_object_context
            self.assertEqual(object1, object1_proxy.item)
            object1.persistent_object_context = None
            self.assertIsNone(object1_proxy.item)

    def test_persistent_object_proxy_calls_listeners_when_initialized_with_object(self):

        r_count = 0
        u_count = 0

        def r(x): nonlocal r_count; r_count += 1
        def u(x): nonlocal u_count; u_count += 1

        persistent_object_context = Persistence.PersistentObjectContext()
        object0 = Persistence.PersistentObject()
        object1 = Persistence.PersistentObject()
        object1_proxy = object0.create_item_proxy(item=object1)
        object1_proxy.on_item_registered = r
        object1_proxy.on_item_unregistered = u
        with contextlib.closing(object1_proxy):
            # register parent and check initial conditions
            object0.persistent_object_context = persistent_object_context
            self.assertEqual(object1, object1_proxy.item)
            self.assertEqual(0, r_count)
            self.assertEqual(0, u_count)
            # register child which was already registered; confirm registered not called
            object1.persistent_object_context = persistent_object_context
            self.assertEqual(0, r_count)  # item never becomes registered; it starts registered
            self.assertEqual(0, u_count)
            # unregister works normal
            object1.persistent_object_context = None
            self.assertEqual(0, r_count)
            self.assertEqual(1, u_count)

    def test_persistent_object_proxy_calls_listeners_once_during_lifecycle(self):

        r_count = 0
        u_count = 0

        def r(x): nonlocal r_count; r_count += 1
        def u(x): nonlocal u_count; u_count += 1

        persistent_object_context = Persistence.PersistentObjectContext()
        object0 = Persistence.PersistentObject()
        object1 = Persistence.PersistentObject()
        object1_proxy = object0.create_item_proxy(item_specifier=Persistence.PersistentObjectSpecifier.read(object1.uuid))
        with contextlib.closing(object1_proxy):
            object1_proxy.on_item_registered = r
            object1_proxy.on_item_unregistered = u
            # register parent, but not child
            object0.persistent_object_context = persistent_object_context
            self.assertEqual(0, r_count)
            self.assertEqual(0, u_count)
            # now register child and ensure register was called
            object1.persistent_object_context = persistent_object_context
            self.assertEqual(object1, object1_proxy.item)
            self.assertEqual(1, r_count)
            self.assertEqual(0, u_count)
            # unregister child and ensure unregistered was called
            object1.persistent_object_context = None
            self.assertEqual(1, r_count)
            self.assertEqual(1, u_count)

    def test_persistent_object_proxy_not_registered_when_already_registered(self):

        r_count = 0
        u_count = 0

        def r(x): nonlocal r_count; r_count += 1
        def u(x): nonlocal u_count; u_count += 1

        persistent_object_context = Persistence.PersistentObjectContext()
        object0 = Persistence.PersistentObject()
        object1 = Persistence.PersistentObject()
        object0.persistent_object_context = persistent_object_context
        object1.persistent_object_context = persistent_object_context
        # both objects are already registered
        object1_proxy = object0.create_item_proxy(item_specifier=Persistence.PersistentObjectSpecifier.read(object1.uuid))
        with contextlib.closing(object1_proxy):
            object1_proxy.on_item_registered = r
            object1_proxy.on_item_unregistered = u
            # registered should not be called because it was already registered
            self.assertEqual(object1, object1_proxy.item)
            self.assertEqual(0, r_count)
            self.assertEqual(0, u_count)
            object1.persistent_object_context = None
            # but unregistered should be called
            self.assertEqual(0, r_count)
            self.assertEqual(1, u_count)

    def test_persistent_object_proxy_does_not_call_listener_when_removed_from_unregistered_parent(self):

        r_count = 0
        u_count = 0

        def r(x): nonlocal r_count; r_count += 1
        def u(x): nonlocal u_count; u_count += 1

        persistent_object_context = Persistence.PersistentObjectContext()
        object0 = Persistence.PersistentObject()
        object1 = Persistence.PersistentObject()
        object1_proxy = object0.create_item_proxy(item_specifier=Persistence.PersistentObjectSpecifier.read(object1.uuid))
        with contextlib.closing(object1_proxy):
            object1_proxy.on_item_registered = r
            object1_proxy.on_item_unregistered = u
            object0.persistent_object_context = persistent_object_context
            # only parent has been registered
            self.assertEqual(0, r_count)
            self.assertEqual(0, u_count)
            object1.persistent_object_context = persistent_object_context
            # now object has been registered
            self.assertEqual(object1, object1_proxy.item)
            self.assertEqual(1, r_count)
            self.assertEqual(0, u_count)
            # unregistered parent first, then object
            object0.persistent_object_context = None
            object1.persistent_object_context = None
            self.assertEqual(1, r_count)
            self.assertEqual(0, u_count)  # parent was already unregistered
