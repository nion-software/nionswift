# standard libraries
import contextlib
import pathlib
import typing
import unittest
import unittest.mock

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.model import FileStorageSystem
from nion.swift.model import Profile
from nion.swift.test import TestContext


Facade.initialize()


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestProjectClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_projects_with_duplicate_uuid_are_allowed_on_different_paths(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = profile_context.profile
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                # add a project reference; it won't be loaded until we reload below
                TestContext.add_project_memory(profile, document_model._project.uuid)
                self.assertEqual(2, len(profile.projects))
            # reload; there will be two project references, but only one project loaded initially
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                profile = typing.cast(Profile.Profile, getattr(document_model, "_profile_for_test"))
                self.assertEqual(2, len(profile.project_references))
                self.assertEqual(1, len(document_model.data_items))

    def test_project_reloads_with_same_uuid(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                project_uuid = document_model._project.uuid
                project_specifier = document_model._project.item_specifier
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                self.assertEqual(project_uuid, document_model._project.uuid)
                profile = typing.cast(Profile.Profile, getattr(document_model, "_profile_for_test"))
                self.assertEqual(document_model._project, profile.persistent_object_context.get_registered_object(project_specifier))

    def test_adding_same_project_raises_error_during_append(self):
        # create two data items in different projects. select the two items in the data panel
        # and create a computation from the two inputs. compute and make sure no errors occur.
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            project_reference1 = TestContext.add_project_memory(profile_context.profile)
            with contextlib.closing(document_controller):
                project_reference = TestContext.MemoryProjectReference()
                project_reference.project_uuid = project_reference1.project_uuid
                project_reference._path = project_reference1._path
                with self.assertRaises(Exception):
                    profile_context.profile.append_project_reference(project_reference)
                project_reference.close()

    # do not import same project (by uuid) twice

    def test_project_name_viewmodel_is_invalid_with_existing_reference(self) -> None:
        with TestContext.MemoryProfileContext() as profile_context:
            profile = profile_context.create_profile()
            project_reference = profile.project_references[0]
            reference_path = project_reference.path
            base_directory = reference_path.parent

            def mock_get_project_reference_by_path(_path: pathlib.Path) -> Profile.ProjectReference | None:
                return project_reference

            def mock_check_project_name_is_available(_name: str, _directory: str) -> FileStorageSystem.ProjectNameResult:
                return FileStorageSystem.ProjectNameResult([], reference_path)  # Return the project path with no errors so it can be checked against the existing references

            with unittest.mock.patch.object(profile, 'get_project_reference_by_path', mock_get_project_reference_by_path):
                with unittest.mock.patch.object(FileStorageSystem.ProjectStorageSystem, 'check_project_name_is_available', mock_check_project_name_is_available):
                    viewmodel = Application.NameProjectViewModel(project_reference.title, str(base_directory), profile, FileStorageSystem.ProjectStorageSystem)
                    viewmodel.update_project_status_label(project_reference.title)
                    self.assertFalse(viewmodel.accept_button_enabled.value)
                    self.assertEqual(viewmodel.project_name_status_label.value, f"Project Reference \"{reference_path.stem}\" already exists, remove it via Choose Project before proceeding")
