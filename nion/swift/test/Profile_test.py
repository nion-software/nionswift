# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Profile
from nion.ui import TestUI


Facade.initialize()


def create_memory_profile_context():
    return Profile.MemoryProfileContext()


class TestProfileClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_profile_with_two_projects_with_data_items_reload(self):
        with create_memory_profile_context() as profile_context:
            profile = profile_context.create_profile()
            profile.add_project_memory()
            document_model = DocumentModel.DocumentModel(profile=profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[0])
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[1])
                self.assertEqual(1, len(document_model.profile.projects[0].data_items))
                self.assertEqual(1, len(document_model.profile.projects[1].data_items))
            document_model = DocumentModel.DocumentModel(profile=profile_context.create_profile())
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.profile.projects))
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(1, len(document_model.profile.projects[0].data_items))
                self.assertEqual(1, len(document_model.profile.projects[1].data_items))
                self.assertEqual(2, len(document_model.display_items))
                self.assertEqual(1, len(document_model.profile.projects[0].display_items))
                self.assertEqual(1, len(document_model.profile.projects[1].display_items))

    def test_display_item_is_added_to_same_project_as_data_item(self):
        with create_memory_profile_context() as profile_context:
            profile = profile_context.create_profile()
            profile.add_project_memory()
            document_model = DocumentModel.DocumentModel(profile=profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[0])
                document_model.append_display_item(DisplayItem.DisplayItem(data_item=data_item))
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[1])
                document_model.append_display_item(DisplayItem.DisplayItem(data_item=data_item))
            document_model = DocumentModel.DocumentModel(profile=profile_context.create_profile())
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(document_model.profile.projects[0].display_items))
                self.assertEqual(2, len(document_model.profile.projects[1].display_items))

    def test_add_data_structure_to_project_reloads(self):
        with create_memory_profile_context() as profile_context:
            profile = profile_context.create_profile()
            profile.add_project_memory()
            document_model = DocumentModel.DocumentModel(profile=profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[0])
                data_struct = document_model.create_data_structure()
                data_struct.set_referenced_object("master", data_item)
                document_model.append_data_structure(data_struct)
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[1])
                data_struct = document_model.create_data_structure()
                data_struct.set_referenced_object("master", data_item)
                document_model.append_data_structure(data_struct)
            document_model = DocumentModel.DocumentModel(profile=profile_context.create_profile())
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(2, len(document_model.data_structures))
                self.assertEqual(1, len(document_model.profile.projects[0].data_structures))
                self.assertEqual(1, len(document_model.profile.projects[1].data_structures))

    def test_computation_added_to_same_project_as_inputs(self):
        with create_memory_profile_context() as profile_context:
            profile = profile_context.create_profile()
            profile.add_project_memory()
            document_model = DocumentModel.DocumentModel(profile=profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[0])
                document_model.get_invert_new(document_model.get_display_item_for_data_item(data_item))
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[1])
                document_model.get_invert_new(document_model.get_display_item_for_data_item(data_item))
            document_model = DocumentModel.DocumentModel(profile=profile_context.create_profile())
            with contextlib.closing(document_model):
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(document_model.computations))
                self.assertEqual(1, len(document_model.profile.projects[0].computations))
                self.assertEqual(1, len(document_model.profile.projects[1].computations))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(document_model.profile.projects[0].display_items))
                self.assertEqual(2, len(document_model.profile.projects[1].display_items))

    def test_connection_added_to_same_project_as_inputs(self):
        with create_memory_profile_context() as profile_context:
            profile = profile_context.create_profile()
            profile.add_project_memory()
            document_model = DocumentModel.DocumentModel(profile=profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[0])
                document_model.get_line_profile_new(document_model.get_display_item_for_data_item(data_item))
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[1])
                document_model.get_line_profile_new(document_model.get_display_item_for_data_item(data_item))
            document_model = DocumentModel.DocumentModel(profile=profile_context.create_profile())
            with contextlib.closing(document_model):
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(document_model.connections))
                self.assertEqual(1, len(document_model.profile.projects[0].connections))
                self.assertEqual(1, len(document_model.profile.projects[1].connections))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(document_model.profile.projects[0].display_items))
                self.assertEqual(2, len(document_model.profile.projects[1].display_items))
