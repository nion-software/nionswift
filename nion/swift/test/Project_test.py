# standard libraries
import contextlib
import copy
import typing
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import Connection
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Profile
from nion.swift.test import TestContext
from nion.ui import TestUI


Facade.initialize()


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestProjectClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_projects_with_duplicate_uuid_are_not_loaded(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = profile_context.profile
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                # add a project reference; it won't be loaded until we reload below
                TestContext.add_project_memory(profile, document_model._project.uuid)
                self.assertEqual(1, len(profile.projects))
            # reload; will try to load two projects with same uuid
            document_model = profile_context.create_document_model(auto_close=False)
            profile = typing.cast(Profile.Profile, getattr(document_model, "_profile_for_test"))
            with contextlib.closing(document_model):
                self.assertEqual(1, len(profile.projects))
                self.assertEqual(1, len(profile.projects[0].data_items))

    def test_project_reloads_with_same_uuid(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                project_uuid = document_model._project.uuid
                project_specifier = document_model._project.item_specifier
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(project_uuid, document_model._project.uuid)
                profile = typing.cast(Profile.Profile, getattr(document_model, "_profile_for_test"))
                self.assertEqual(document_model._project, profile.persistent_object_context.get_registered_object(project_specifier))

    def test_adding_same_project_raises_error_during_append(self):
        # create two data items in different projects. select the two items in the data panel
        # and create a computation from the two inputs. compute and make sure no errors occur.
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            TestContext.add_project_memory(profile_context.profile)
            with contextlib.closing(document_controller):
                project_reference = TestContext.MemoryProjectReference()
                project_reference.project_uuid = document_model._project.uuid
                with self.assertRaises(Exception):
                    profile_context.profile.append_project_reference(project_reference)

    # do not import same project (by uuid) twice
