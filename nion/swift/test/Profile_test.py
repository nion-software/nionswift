# standard libraries
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.test import TestContext
from nion.ui import TestUI


Facade.initialize()


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestProfileClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_closing_window_unloads_project_referemnce(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile()
            profile.read_profile()
            self.app._set_profile_for_test(profile)
            TestContext.add_project_memory(profile, load=False)
            document_controller = self.app.open_project_window(profile.project_references[0])
            # check conditions
            self.assertEqual(2, len(profile.project_references))
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])
            document_controller.request_close()
            self.assertEqual("unloaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])

    def test_switching_projects_and_back(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile()
            profile.read_profile()
            self.app._set_profile_for_test(profile)
            TestContext.add_project_memory(profile, load=False)
            # load first project and check conditions
            document_controller = self.app.open_project_window(profile.project_references[0])
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])
            # switch projects and check conditions
            document_controller.request_close()
            document_controller = self.app.open_project_window(profile.project_references[1])
            self.assertEqual("unloaded", profile.project_references[0].project_info[2])
            self.assertEqual("loaded", profile.project_references[1].project_info[2])
            # switch projects again and check conditions
            document_controller.request_close()
            document_controller = self.app.open_project_window(profile.project_references[0])
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])
            document_controller.request_close()

    def test_switching_projects_with_related_items(self):
        # this tests that project gets removed from persistent object context
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile()
            profile.read_profile()
            self.app._set_profile_for_test(profile)
            TestContext.add_project_memory(profile, load=False)
            # load first project and check conditions
            document_controller = self.app.open_project_window(profile.project_references[0])
            document_controller.document_model.append_data_item(DataItem.DataItem(numpy.zeros((2, 2))))
            document_controller._perform_processing(document_controller.document_model.display_items[0], None, document_controller.document_model.get_fft_new)
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])
            self.assertEqual(2, len(document_controller.document_model.data_items))
            # switch projects and check conditions
            document_controller.request_close()
            document_controller = self.app.open_project_window(profile.project_references[1])
            self.assertEqual("unloaded", profile.project_references[0].project_info[2])
            self.assertEqual("loaded", profile.project_references[1].project_info[2])
            # switch projects again and check conditions
            document_controller.request_close()
            document_controller = self.app.open_project_window(profile.project_references[0])
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])
            self.assertEqual(2, len(document_controller.document_model.data_items))
            document_controller.request_close()

    def test_forget_project(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile()
            profile.read_profile()
            self.app._set_profile_for_test(profile)
            TestContext.add_project_memory(profile, load=False)
            # load first project and check conditions
            document_controller = self.app.open_project_window(profile.project_references[0])
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])
            # forget project and check conditions
            profile.remove_project_reference(profile.project_references[1])
            self.assertEqual(1, len(profile.project_references))
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            # clean up
            document_controller.close()

    def test_create_project(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile()
            profile.read_profile()
            self.app._set_profile_for_test(profile)
            document_controller = self.app.open_project_window(profile.project_references[0])
            # check preconditions
            self.assertEqual(1, len(self.app.windows))
            self.assertEqual(1, len(profile.project_references))
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            # add project, check
            project_reference2 = profile.add_project_memory(load=False)
            self.assertEqual(2, len(profile.project_references))
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])
            self.assertEqual(project_reference2, profile.project_references[1])
            self.assertEqual(1, len(self.app.windows))
            # clean up
            document_controller.close()

    def test_forget_loaded_project_not_allowed(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile()
            profile.read_profile()
            self.app._set_profile_for_test(profile)
            TestContext.add_project_memory(profile, load=False)
            # load first project and check conditions
            document_controller = self.app.open_project_window(profile.project_references[0])
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])
            # forget project and check conditions
            with self.assertRaises(Exception):
                profile.remove_project_reference(profile.project_references[0])
            self.assertEqual(2, len(profile.project_references))
            self.assertEqual("loaded", profile.project_references[0].project_info[2])
            self.assertEqual("unloaded", profile.project_references[1].project_info[2])
            # clean up
            document_controller.close()

    # TODO: creating new project
    # TODO: opening project from file
    # TODO: opening same project is not allowed
    # TODO: recent menu is sorted by date and limited
    # TODO: upgrade project
