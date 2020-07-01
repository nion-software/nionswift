# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import DataItem
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
                self.assertEqual(1, len(document_model.projects[0].data_items))
                self.assertEqual(1, len(document_model.projects[1].data_items))
            document_model = DocumentModel.DocumentModel(profile=profile_context.create_profile())
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.projects))
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(1, len(document_model.projects[0].data_items))
                self.assertEqual(1, len(document_model.projects[1].data_items))
                self.assertEqual(2, len(document_model.display_items))
                self.assertEqual(1, len(document_model.projects[0].display_items))
                self.assertEqual(1, len(document_model.projects[1].display_items))

    def test_work_project_cannot_be_removed(self):
        with create_memory_profile_context() as profile_context:
            profile = profile_context.create_profile()
            profile.add_project_memory()
            document_model = DocumentModel.DocumentModel(profile=profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[0])
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[1])
                self.assertEqual(profile.work_project, profile.projects[0])
                self.assertEqual(2, len(profile.projects))
                profile.remove_project_reference(profile.project_references[0])  # work profile
                self.assertEqual(2, len(profile.projects))
