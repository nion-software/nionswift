# standard libraries
import logging
import unittest
import unittest.mock

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


def press_ok_and_complete(*args, **kwargs):
    kwargs["completion_fn"]()

def press_ok_cancel_and_ok_complete(*args, **kwargs):
    kwargs["completion_fn"](True)

def press_ok_cancel_and_cancel_complete(*args, **kwargs):
    kwargs["completion_fn"](False)


class TestProfileClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

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
            self.assertEqual("loaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)
            document_controller.request_close()
            self.assertEqual("unloaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)

    def test_switching_projects_and_back(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile()
            profile.read_profile()
            app = profile_context.create_application()
            app._set_profile_for_test(profile)
            TestContext.add_project_memory(profile, load=False)
            # load first project and check conditions
            document_controller = app.open_project_window(profile.project_references[0])
            self.assertEqual("loaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)
            # switch projects and check conditions
            document_controller.request_close()
            document_controller = app.open_project_window(profile.project_references[1])
            self.assertEqual("unloaded", profile.project_references[0].project_state)
            self.assertEqual("loaded", profile.project_references[1].project_state)
            # switch projects again and check conditions
            document_controller.request_close()
            document_controller = app.open_project_window(profile.project_references[0])
            self.assertEqual("loaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)
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
            document_controller._perform_processing(document_controller.document_model.display_items[0], document_controller.document_model.display_items[0].data_item, None, document_controller.document_model.get_fft_new)
            document_controller.document_model.recompute_all()
            self.assertEqual("loaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)
            self.assertEqual(2, len(document_controller.document_model.data_items))
            # switch projects and check conditions
            document_controller.request_close()
            document_controller = self.app.open_project_window(profile.project_references[1])
            self.assertEqual("unloaded", profile.project_references[0].project_state)
            self.assertEqual("loaded", profile.project_references[1].project_state)
            # switch projects again and check conditions
            document_controller.request_close()
            document_controller = self.app.open_project_window(profile.project_references[0])
            self.assertEqual("loaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)
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
            self.assertEqual("loaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)
            # forget project and check conditions
            profile.remove_project_reference(profile.project_references[1])
            self.assertEqual(1, len(profile.project_references))
            self.assertEqual("loaded", profile.project_references[0].project_state)
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
            self.assertEqual("loaded", profile.project_references[0].project_state)
            # add project, check
            project_reference2 = profile.add_project_memory(load=False)
            self.assertEqual(2, len(profile.project_references))
            self.assertEqual("loaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)
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
            self.assertEqual("loaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)
            # forget project and check conditions
            with self.assertRaises(Exception):
                profile.remove_project_reference(profile.project_references[0])
            self.assertEqual(2, len(profile.project_references))
            self.assertEqual("loaded", profile.project_references[0].project_state)
            self.assertEqual("unloaded", profile.project_references[1].project_state)
            # clean up
            document_controller.close()

    def test_launch_with_no_project_then_cancel_choose_dialog(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile(add_project=False)
            profile.read_profile()
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app._set_profile_for_test(profile)
            app.initialize(load_plug_ins=False)
            try:
                # ensure no project references
                self.assertEqual(0, len(profile.project_references))
                # set up mock calls to get through start call and check conditions
                app.show_choose_project_dialog = unittest.mock.Mock()
                # start the app
                app.start(profile=profile)
                # check the mock calls
                app.show_choose_project_dialog.assert_called_once()
                # ensure no project is loaded
                self.assertEqual(0, len(profile.project_references))
                self.assertEqual(0, len(app.windows))
            finally:
                app._set_profile_for_test(None)
                app.exit()
                app.deinitialize()

    def test_launch_with_no_project_then_cancel_open_dialog(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile(add_project=False)
            profile.read_profile()
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app._set_profile_for_test(profile)
            app.initialize(load_plug_ins=False)
            try:
                # ensure no project references
                self.assertEqual(0, len(profile.project_references))
                # set up mock calls to get through start call and check conditions
                app.ui.get_file_paths_dialog = unittest.mock.Mock(return_value=([], str(), str()))
                app.show_ok_dialog = unittest.mock.Mock()
                app.show_ok_dialog.side_effect = press_ok_and_complete
                app.show_choose_project_dialog = unittest.mock.Mock()
                app.show_choose_project_dialog.side_effect = app.show_open_project_dialog
                # start the app
                app.start(profile=profile)
                # check the mock calls
                app.ui.get_file_paths_dialog.assert_called_once()
                app.show_choose_project_dialog.assert_called_once()
                app.show_ok_dialog.assert_not_called()
                # ensure no project is loaded
                self.assertEqual(0, len(profile.project_references))
                self.assertEqual(0, len(app.windows))
            finally:
                app._set_profile_for_test(None)
                app.exit()
                app.deinitialize()

    def test_launch_with_no_project_then_open_a_project(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile(add_project=False)
            profile.read_profile()
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app._set_profile_for_test(profile)
            app.initialize(load_plug_ins=False)
            try:
                # ensure no project references
                self.assertEqual(0, len(profile.project_references))

                # set up mock calls to get through start call
                profile.open_project = unittest.mock.Mock()
                profile.open_project.side_effect = lambda x: TestContext.add_project_memory(profile, load=False)
                app.ui.get_file_paths_dialog = unittest.mock.Mock(return_value=(["PATH"], str(), str()))
                app.show_ok_dialog = unittest.mock.Mock()
                app.show_ok_dialog.side_effect = press_ok_and_complete
                app.show_choose_project_dialog = unittest.mock.Mock()
                app.show_choose_project_dialog.side_effect = app.show_open_project_dialog
                logging.getLogger("loader").setLevel = unittest.mock.Mock()  # ignore this call

                # start the app
                app.start(profile=profile)

                # check the mock calls
                app.ui.get_file_paths_dialog.assert_called_once()
                profile.open_project.assert_called_once()
                app.show_choose_project_dialog.assert_called_once()
                app.show_ok_dialog.assert_not_called()

                # ensure a single project is loaded
                self.assertEqual(1, len(profile.project_references))
                self.assertEqual("loaded", profile.project_references[0].project_state)
                self.assertEqual(1, len(app.windows))
            finally:
                app._set_profile_for_test(None)
                app.exit()
                app.deinitialize()

    def test_launch_with_no_project_then_open_a_project_with_error(self):
        # test both json error and general storage error
        for uuid_error, storage_error in ((True, False), (False, True)):
            with self.subTest(uuid_error=uuid_error, storage_error=storage_error):
                with create_memory_profile_context() as profile_context:
                    # use lower level calls to create the profile and open the window via the app
                    profile = profile_context.create_profile(add_project=False)
                    profile.read_profile()
                    app = Application.Application(TestUI.UserInterface(), set_global=False)
                    app._set_profile_for_test(profile)
                    app.initialize(load_plug_ins=False)
                    try:
                        # ensure no project references
                        self.assertEqual(0, len(profile.project_references))

                        # set up mock calls to get through start call
                        def setup_bad_project(args):
                            project_reference = TestContext.add_project_memory(profile, load=False, make_uuid_error=uuid_error, make_storage_error=storage_error)
                            return project_reference

                        app.show_choose_project_dialog = unittest.mock.Mock()
                        app.show_choose_project_dialog.side_effect = app.show_open_project_dialog
                        profile.open_project = unittest.mock.Mock()
                        profile.open_project.side_effect = setup_bad_project
                        app.ui.get_file_paths_dialog = unittest.mock.Mock()
                        app.ui.get_file_paths_dialog.side_effect = [(["PATH"], str(), str()), ([], str(), str())]
                        app.show_ok_dialog = unittest.mock.Mock()
                        app.show_ok_dialog.side_effect = press_ok_and_complete
                        logging.getLogger("loader").setLevel = unittest.mock.Mock()  # ignore this call

                        # start the app
                        app.start(profile=profile)

                        # check the mock calls
                        self.assertEqual(2, len(app.ui.get_file_paths_dialog.mock_calls))
                        profile.open_project.assert_called_once()
                        app.show_ok_dialog.assert_called_once()

                        # ensure a single project is loaded
                        self.assertEqual(1, len(profile.project_references))
                        self.assertEqual("invalid", profile.project_references[0].project_state)
                        self.assertEqual(0, len(app.windows))
                    finally:
                        app._set_profile_for_test(None)
                        app.exit()
                        app.deinitialize()

    def test_launch_with_no_project_then_open_a_project_needing_upgrade_and_cancel(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile(add_project=False)
            profile.read_profile()
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app._set_profile_for_test(profile)
            app.initialize(load_plug_ins=False)
            try:
                # ensure no project references
                self.assertEqual(0, len(profile.project_references))

                # set up mock calls to get through start call
                def setup_needs_upgrade_project(args):
                    project_reference = TestContext.add_project_memory(profile, load=False, d={"version": 0})
                    return project_reference

                profile.open_project = unittest.mock.Mock()
                profile.open_project.side_effect = setup_needs_upgrade_project
                app.ui.get_file_paths_dialog = unittest.mock.Mock()
                app.ui.get_file_paths_dialog = unittest.mock.Mock(return_value=(["PATH"], str(), str()))
                app.show_ok_cancel_dialog = unittest.mock.Mock()
                app.show_ok_cancel_dialog.side_effect = press_ok_cancel_and_cancel_complete
                app.show_choose_project_dialog = unittest.mock.Mock()
                app.show_choose_project_dialog.side_effect = app.show_open_project_dialog
                logging.getLogger("loader").setLevel = unittest.mock.Mock()  # ignore this call

                # start the app
                app.start(profile=profile)

                # check the mock calls
                self.assertEqual(1, len(app.ui.get_file_paths_dialog.mock_calls))
                profile.open_project.assert_called_once()
                app.show_choose_project_dialog.assert_called_once()
                app.show_ok_cancel_dialog.assert_called_once()

                # ensure a single project is loaded
                self.assertEqual(1, len(profile.project_references))
                self.assertEqual("needs_upgrade", profile.project_references[0].project_state)
                self.assertEqual(0, len(app.windows))
            finally:
                app._set_profile_for_test(None)
                app.exit()
                app.deinitialize()

    def test_launch_with_no_project_then_open_a_project_needing_upgrade_and_proceed(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile(add_project=False)
            profile.read_profile()
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app._set_profile_for_test(profile)
            app.initialize(load_plug_ins=False)
            try:
                # ensure no project references
                self.assertEqual(0, len(profile.project_references))

                # set up mock calls to get through start call
                def setup_needs_upgrade_project(args):
                    project_reference = TestContext.add_project_memory(profile, load=False, d={"version": 0})
                    return project_reference

                profile.open_project = unittest.mock.Mock()
                profile.open_project.side_effect = setup_needs_upgrade_project
                app.ui.get_file_paths_dialog = unittest.mock.Mock()
                app.ui.get_file_paths_dialog = unittest.mock.Mock(return_value=(["PATH"], str(), str()))
                app.show_ok_cancel_dialog = unittest.mock.Mock()
                app.show_ok_cancel_dialog.side_effect = press_ok_cancel_and_ok_complete
                app.show_choose_project_dialog = unittest.mock.Mock()
                app.show_choose_project_dialog.side_effect = app.show_open_project_dialog
                logging.getLogger("loader").setLevel = unittest.mock.Mock()  # ignore this call

                # start the app
                app.start(profile=profile)

                # check the mock calls
                self.assertEqual(1, len(app.ui.get_file_paths_dialog.mock_calls))
                profile.open_project.assert_called_once()
                app.show_choose_project_dialog.assert_called_once()
                app.show_ok_cancel_dialog.assert_called_once()

                # ensure a single project is loaded
                self.assertEqual(1, len(profile.project_references))
                self.assertEqual("loaded", profile.project_references[0].project_state)
                self.assertEqual(1, len(app.windows))
            finally:
                app._set_profile_for_test(None)
                app.exit()
                app.deinitialize()

    def test_launch_with_no_project_then_open_a_project_needing_upgrade_but_unable_to_upgrade(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile(add_project=False)
            profile.read_profile()
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app._set_profile_for_test(profile)
            app.initialize(load_plug_ins=False)
            try:
                # ensure no project references
                self.assertEqual(0, len(profile.project_references))

                # set up mock calls to get through start call
                def setup_needs_upgrade_project(args):
                    project_reference = TestContext.add_project_memory(profile, load=False, d={"version": 0})
                    return project_reference

                profile.open_project = unittest.mock.Mock()
                profile.open_project.side_effect = setup_needs_upgrade_project
                app.ui.get_file_paths_dialog = unittest.mock.Mock()
                app.ui.get_file_paths_dialog = unittest.mock.Mock(return_value=(["PATH"], str(), str()))
                app.show_choose_project_dialog = unittest.mock.Mock()
                app.show_choose_project_dialog.side_effect = app.show_open_project_dialog
                app.show_ok_cancel_dialog = unittest.mock.Mock()
                app.show_ok_cancel_dialog.side_effect = press_ok_cancel_and_ok_complete
                app.show_ok_dialog = unittest.mock.Mock()
                profile.upgrade = unittest.mock.Mock()
                profile.upgrade.side_effect = FileExistsError()
                logging.getLogger("loader").setLevel = unittest.mock.Mock()  # ignore this call

                # start the app
                app.start(profile=profile)

                # check the mock calls
                self.assertEqual(1, len(app.ui.get_file_paths_dialog.mock_calls))
                profile.open_project.assert_called_once()
                app.show_choose_project_dialog.assert_called_once()
                app.show_ok_cancel_dialog.assert_called_once()
                app.show_ok_dialog.assert_called_once()

                # ensure a single project is loaded
                self.assertEqual(1, len(profile.project_references))
                self.assertEqual(0, len(app.windows))
            finally:
                app._set_profile_for_test(None)
                app.exit()
                app.deinitialize()

    def test_switching_project_reloads_new_project_on_relaunch(self):
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile(add_project=False)
            profile.read_profile()
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app._set_profile_for_test(profile)
            TestContext.add_project_memory(profile, load=False)
            TestContext.add_project_memory(profile, load=False)
            app.initialize(load_plug_ins=False)
            try:
                # ensure one project reference
                self.assertEqual(2, len(profile.project_references))
                profile.last_project_reference = profile.project_references[0].uuid
                logging.getLogger("loader").setLevel = unittest.mock.Mock()  # ignore this call

                # start the app
                app.start(profile=profile)

                # ensure a single project is loaded
                self.assertEqual(2, len(profile.project_references))
                self.assertEqual("loaded", profile.project_references[0].project_state)
                self.assertEqual("unloaded", profile.project_references[1].project_state)
                self.assertEqual(1, len(app.windows))
                self.assertEqual(profile.last_project_reference, profile.project_references[0].uuid)

                # switch project and check
                app.switch_project_reference(profile.project_references[1])
                self.assertEqual("unloaded", profile.project_references[0].project_state)
                self.assertEqual("loaded", profile.project_references[1].project_state)
                self.assertEqual(1, len(app.windows))
                self.assertEqual(profile.last_project_reference, profile.project_references[1].uuid)
            finally:
                app._set_profile_for_test(None)
                app.exit()
                app.deinitialize()

            # reload and check
            profile = profile_context.create_profile(add_project=False)
            profile.read_profile()
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app._set_profile_for_test(profile)
            app.initialize(load_plug_ins=False)
            try:
                # ensure two project references
                self.assertEqual(2, len(profile.project_references))
                profile.last_project_reference = profile.project_references[0].uuid

                # start the app
                app.start(profile=profile)

                # switch project and check
                app.switch_project_reference(profile.project_references[1])
                self.assertEqual("unloaded", profile.project_references[0].project_state)
                self.assertEqual("loaded", profile.project_references[1].project_state)
                self.assertEqual(1, len(app.windows))
                self.assertEqual(profile.last_project_reference, profile.project_references[1].uuid)
            finally:
                app._set_profile_for_test(None)
                app.exit()
                app.deinitialize()

    def test_switch_to_project_with_error(self):
        # test both json error and general storage error
        for uuid_error, storage_error in ((True, False), (False, True)):
            with self.subTest(uuid_error=uuid_error, storage_error=storage_error):
                with create_memory_profile_context() as profile_context:
                    # use lower level calls to create the profile and open the window via the app
                    profile = profile_context.create_profile(add_project=False)
                    profile.read_profile()
                    app = Application.Application(TestUI.UserInterface(), set_global=False)
                    app._set_profile_for_test(profile)
                    TestContext.add_project_memory(profile, load=False)
                    TestContext.add_project_memory(profile, load=False)
                    app.initialize(load_plug_ins=False)
                    try:
                        # ensure two project references
                        self.assertEqual(2, len(profile.project_references))
                        profile.last_project_reference = profile.project_references[0].uuid
                        logging.getLogger("loader").setLevel = unittest.mock.Mock()  # ignore this call
                        app.show_choose_project_dialog = unittest.mock.Mock()
                        app.show_choose_project_dialog.side_effect = app.show_open_project_dialog

                        # start the app
                        app.start(profile=profile)

                        # ensure a single project is loaded
                        self.assertEqual(2, len(profile.project_references))
                        self.assertEqual("loaded", profile.project_references[0].project_state)
                        self.assertEqual("unloaded", profile.project_references[1].project_state)
                        self.assertEqual(1, len(app.windows))
                        self.assertEqual(profile.last_project_reference, profile.project_references[0].uuid)

                        # switching to an error project should display an ok message with an error, then the file
                        # open dialog (which will be cancelled). no windows should be open at the end.

                        # set up mock calls to get through the switch.
                        if uuid_error:
                            profile.read_project = unittest.mock.Mock()
                            profile.read_project.side_effect = Exception()
                        if storage_error:
                            profile.project_references[1].make_storage = unittest.mock.Mock()
                            profile.project_references[1].make_storage.side_effect = Exception()
                        app.ui.get_file_paths_dialog = unittest.mock.Mock()
                        app.ui.get_file_paths_dialog.side_effect = [([], str(), str()), ([], str(), str())]
                        app.show_ok_dialog = unittest.mock.Mock()
                        app.show_ok_dialog.side_effect = press_ok_and_complete
                        logging.getLogger("loader").setLevel = unittest.mock.Mock()  # ignore this call

                        # switch project and check
                        app.switch_project_reference(profile.project_references[1])
                        app.ui.get_file_paths_dialog.assert_called_once()
                        app.show_ok_dialog.assert_called_once()
                        self.assertEqual("unloaded", profile.project_references[0].project_state)
                        self.assertEqual("unloaded", profile.project_references[1].project_state)
                        self.assertEqual(0, len(app.windows))
                        self.assertEqual(profile.last_project_reference, profile.project_references[0].uuid)
                    finally:
                        app._set_profile_for_test(None)
                        app.exit()
                        app.deinitialize()

    def test_invalid_last_project_forces_choose_dialog(self) -> None:
        with create_memory_profile_context() as profile_context:
            # use lower level calls to create the profile and open the window via the app
            profile = profile_context.create_profile(add_project=False)
            profile.read_profile()
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app._set_profile_for_test(profile)
            TestContext.add_project_memory(profile, load=False, valid=False)
            app.initialize(load_plug_ins=False)
            try:
                profile.last_project_reference = profile.project_references[0].uuid
                logging.getLogger("loader").setLevel = unittest.mock.Mock()  # ignore this call
                # ensure one project reference
                self.assertEqual(1, len(profile.project_references))
                # set up mock calls to get through start call and check conditions
                app.show_choose_project_dialog = unittest.mock.Mock()
                # start the app
                app.start(profile=profile)
                # check the mock calls
                app.show_choose_project_dialog.assert_called_once()
            finally:
                app._set_profile_for_test(None)
                app.exit()
                app.deinitialize()

    # TODO: creating new project
    # TODO: opening project from file
    # TODO: opening same project is not allowed
    # TODO: recent menu is sorted by date and limited
    # TODO: upgrade project
