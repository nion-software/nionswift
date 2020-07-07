# standard libraries
import contextlib
import copy
import unittest
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import Facade
from nion.swift.model import Connection
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Project
from nion.swift.test import TestContext
from nion.ui import TestUI


Facade.initialize()


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestProjectClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_display_item_is_added_to_same_project_as_data_item(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[0])
                document_model.append_display_item(DisplayItem.DisplayItem(data_item=data_item))
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[1])
                document_model.append_display_item(DisplayItem.DisplayItem(data_item=data_item))
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(document_model.projects[0].display_items))
                self.assertEqual(2, len(document_model.projects[1].display_items))

    def test_add_data_structure_to_project_reloads(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(2, len(document_model.data_structures))
                self.assertEqual(1, len(document_model.projects[0].data_structures))
                self.assertEqual(1, len(document_model.projects[1].data_structures))

    def test_computation_added_to_same_project_as_inputs(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[0])
                document_model.get_invert_new(document_model.get_display_item_for_data_item(data_item))
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[1])
                document_model.get_invert_new(document_model.get_display_item_for_data_item(data_item))
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(document_model.computations))
                self.assertEqual(1, len(document_model.projects[0].computations))
                self.assertEqual(1, len(document_model.projects[1].computations))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(document_model.projects[0].display_items))
                self.assertEqual(2, len(document_model.projects[1].display_items))
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(document_model.computations))
                self.assertEqual(1, len(document_model.projects[0].computations))
                self.assertEqual(1, len(document_model.projects[1].computations))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(document_model.projects[0].display_items))
                self.assertEqual(2, len(document_model.projects[1].display_items))

    def test_connection_added_to_same_project_as_inputs(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                # make 1st connection between two data items
                data_item1 = DataItem.DataItem(numpy.ones((4, 4)))
                document_model.append_data_item(data_item1, project=profile.projects[0])
                display_item1 = document_model.get_display_item_for_data_item(data_item1)
                data_item2 = DataItem.DataItem(numpy.ones((4, 4)))
                document_model.append_data_item(data_item2, project=profile.projects[0])
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                connection = Connection.PropertyConnection(display_item1, "title", display_item2, "title", parent=data_item1)
                document_model.append_connection(connection)
                # make 2nd connection between two data items
                data_item1 = DataItem.DataItem(numpy.ones((4, 4)))
                document_model.append_data_item(data_item1, project=profile.projects[1])
                display_item1 = document_model.get_display_item_for_data_item(data_item1)
                data_item2 = DataItem.DataItem(numpy.ones((4, 4)))
                document_model.append_data_item(data_item2, project=profile.projects[1])
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                connection = Connection.PropertyConnection(display_item1, "title", display_item2, "title", parent=data_item1)
                document_model.append_connection(connection)
                # check assumptions
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(document_model.connections))
                self.assertEqual(1, len(document_model.projects[0].connections))
                self.assertEqual(1, len(document_model.projects[1].connections))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(document_model.projects[0].display_items))
                self.assertEqual(2, len(document_model.projects[1].display_items))
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                # check after reload
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(document_model.connections))
                self.assertEqual(1, len(document_model.projects[0].connections))
                self.assertEqual(1, len(document_model.projects[1].connections))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(document_model.projects[0].display_items))
                self.assertEqual(2, len(document_model.projects[1].display_items))

    def test_items_with_duplicate_uuid_are_loaded_properly(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[0])
            project_keys = list(profile_context.x_data_properties_map.keys())
            profile_context.x_data_properties_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_properties_map[project_keys[0]])
            profile_context.x_data_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_map[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]] = copy.deepcopy(profile_context.x_project_properties[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]]["uuid"] = str(project_keys[1])
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.projects))
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(1, len(document_model.projects[0].data_items))
                self.assertEqual(1, len(document_model.projects[1].data_items))
                self.assertEqual(2, len(document_model.display_items))
                self.assertEqual(1, len(document_model.projects[0].display_items))
                self.assertEqual(1, len(document_model.projects[1].display_items))

    def test_projects_with_duplicate_uuid_are_not_loaded(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item, project=profile.projects[0])
                # add a project reference; it won't be loaded until we reload below
                TestContext.add_project_memory(profile, profile.projects[0].uuid)
                self.assertEqual(1, len(profile.projects))
            # reload; will try to load two projects with same uuid
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                self.assertEqual(1, len(profile.projects))
                self.assertEqual(1, len(profile.projects[0].data_items))

    def test_display_items_between_items_with_duplicated_uuids_are_connected_per_project(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 1), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[0])
                data_item2 = DataItem.DataItem(numpy.ones((16, 1), numpy.float))
                document_model.append_data_item(data_item2, project=profile.projects[0])
                document_model.display_items[0].append_display_data_channel_for_data_item(data_item2)
            project_keys = list(profile_context.x_data_properties_map.keys())
            profile_context.x_data_properties_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_properties_map[project_keys[0]])
            profile_context.x_data_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_map[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]] = copy.deepcopy(profile_context.x_project_properties[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]]["uuid"] = str(project_keys[1])
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                project0 = document_model.projects[0]
                project1 = document_model.projects[1]
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(project0.display_items))
                self.assertEqual(2, len(project1.display_items))
                self.assertEqual(2, len(set(project0.display_items[0].data_items).intersection(set(project0.data_items))))
                self.assertEqual(2, len(set(project1.display_items[0].data_items).intersection(set(project1.data_items))))
                for item in project0.display_items[0].data_items:
                    self.assertEqual(project0, Project.get_project_for_item(item))
                for item in project1.display_items[0].data_items:
                    self.assertEqual(project1, Project.get_project_for_item(item))

    def test_connections_between_items_with_duplicated_uuids_are_connected_per_project(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                data_item1 = DataItem.DataItem(numpy.ones((4, 4)))
                document_model.append_data_item(data_item1, project=profile.projects[0])
                display_item1 = document_model.get_display_item_for_data_item(data_item1)
                data_item2 = DataItem.DataItem(numpy.ones((4, 4)))
                document_model.append_data_item(data_item2, project=profile.projects[0])
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                connection = Connection.PropertyConnection(display_item1, "title", display_item2, "title", parent=data_item1)
                document_model.append_connection(connection)
            project_keys = list(profile_context.x_data_properties_map.keys())
            profile_context.x_data_properties_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_properties_map[project_keys[0]])
            profile_context.x_data_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_map[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]] = copy.deepcopy(profile_context.x_project_properties[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]]["uuid"] = str(project_keys[1])
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                project0 = document_model.projects[0]
                project1 = document_model.projects[1]
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(document_model.connections))
                self.assertEqual(1, len(project0.connections))
                self.assertEqual(1, len(project1.connections))
                self.assertEqual(4, len(document_model.display_items))
                self.assertEqual(2, len(project0.display_items))
                self.assertEqual(2, len(project1.display_items))
                for item in project0.connections[0].connected_items:
                    self.assertEqual(project0, Project.get_project_for_item(item))
                for item in project1.connections[0].connected_items:
                    self.assertEqual(project1, Project.get_project_for_item(item))

    def test_computations_between_items_with_duplicated_uuids_are_connected_per_project(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[0])
                document_model.get_invert_new(document_model.get_display_item_for_data_item(data_item))
            project_keys = list(profile_context.x_data_properties_map.keys())
            profile_context.x_data_properties_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_properties_map[project_keys[0]])
            profile_context.x_data_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_map[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]] = copy.deepcopy(profile_context.x_project_properties[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]]["uuid"] = str(project_keys[1])
            # adjust the computations to be project-relative specifiers
            profile_context.x_project_properties[project_keys[0]]["computations"][0]["variables"][0]["specifier"].pop("context_uuid")
            profile_context.x_project_properties[project_keys[1]]["computations"][0]["variables"][0]["specifier"].pop("context_uuid")
            # now reload and make sure everything gets resolved properly
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                project0 = document_model.projects[0]
                project1 = document_model.projects[1]
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(document_model.computations))
                self.assertEqual(1, len(project0.computations))
                self.assertEqual(1, len(project1.computations))
                for item in project0.computations[0].input_items:
                    self.assertEqual(project0, Project.get_project_for_item(item))
                for item in project1.computations[0].input_items:
                    self.assertEqual(project1, Project.get_project_for_item(item))

    def test_undo_restores_item_with_proper_project(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[0])
            project_keys = list(profile_context.x_data_properties_map.keys())
            profile_context.x_data_properties_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_properties_map[project_keys[0]])
            profile_context.x_data_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_map[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]] = copy.deepcopy(profile_context.x_project_properties[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]]["uuid"] = str(project_keys[1])
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                project0 = document_model.projects[0]
                project1 = document_model.projects[1]
                for item in project0.display_items[0].data_items:
                    assert item in document_model.data_items
                    self.assertEqual(project0, Project.get_project_for_item(item))
                for item in project1.display_items[0].data_items:
                    assert item in document_model.data_items
                    self.assertEqual(project1, Project.get_project_for_item(item))
                assert project0.display_items[0] in document_model.display_items
                assert project1.display_items[0] in document_model.display_items
                with contextlib.closing(document_model.remove_data_item_with_log(project0.data_items[0], safe=True)) as undelete_log:
                    document_model.undelete_all(undelete_log)
                assert project0.display_items[0] in document_model.display_items
                assert project1.display_items[0] in document_model.display_items
                for item in project0.display_items[0].data_items:
                    assert item in document_model.data_items
                    self.assertEqual(project0, Project.get_project_for_item(item))
                for item in project1.display_items[0].data_items:
                    assert item in document_model.data_items
                    self.assertEqual(project1, Project.get_project_for_item(item))
                with contextlib.closing(document_model.remove_data_item_with_log(project1.data_items[0], safe=True)) as undelete_log:
                    document_model.undelete_all(undelete_log)
                assert project0.display_items[0] in document_model.display_items
                assert project1.display_items[0] in document_model.display_items
                for item in project0.display_items[0].data_items:
                    assert item in document_model.data_items
                    self.assertEqual(project0, Project.get_project_for_item(item))
                for item in project1.display_items[0].data_items:
                    assert item in document_model.data_items
                    self.assertEqual(project1, Project.get_project_for_item(item))

    def test_new_computation_is_bound_to_proper_project(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.float))
                document_model.append_data_item(data_item, project=profile.projects[0])
            project_keys = list(profile_context.x_data_properties_map.keys())
            profile_context.x_data_properties_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_properties_map[project_keys[0]])
            profile_context.x_data_map[project_keys[1]] = copy.deepcopy(profile_context.x_data_map[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]] = copy.deepcopy(profile_context.x_project_properties[project_keys[0]])
            profile_context.x_project_properties[project_keys[1]]["uuid"] = str(project_keys[1])
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                project0 = document_model.projects[0]
                project1 = document_model.projects[1]
                document_model.get_invert_new(document_model.get_display_item_for_data_item(project0.data_items[0]))
                document_model.get_invert_new(document_model.get_display_item_for_data_item(project1.data_items[0]))
                for item in project0.computations[0].input_items:
                    self.assertEqual(project0, Project.get_project_for_item(item))
                for item in project1.computations[0].input_items:
                    self.assertEqual(project1, Project.get_project_for_item(item))

    def test_data_item_in_computation_is_bound_to_its_own_project(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            item_uuid = uuid.uuid4()
            with contextlib.closing(document_model):
                data_item0 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid)
                document_model.append_data_item(data_item0, project=profile.projects[0])
                display_item0 = document_model.get_display_item_for_data_item(data_item0)
                document_model.get_invert_new(display_item0)
                data_item1 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid)
                document_model.append_data_item(data_item1, project=profile.projects[1])
                display_item1 = document_model.get_display_item_for_data_item(data_item1)
                document_model.get_invert_new(display_item1)
                document_model.recompute_all()
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(profile.projects[0].data_items))
                self.assertEqual(2, len(profile.projects[1].data_items))
                self.assertEqual(1, len(profile.projects[0].computations))
                self.assertEqual(1, len(profile.projects[1].computations))
                self.assertEqual(data_item0, list(profile.projects[0].computations[0].input_items)[0])
                self.assertEqual(data_item1, list(profile.projects[1].computations[0].input_items)[0])
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            data_item0 = document_model.data_items[0]
            data_item1 = document_model.data_items[2]
            with contextlib.closing(document_model):
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(profile.projects[0].data_items))
                self.assertEqual(2, len(profile.projects[1].data_items))
                self.assertEqual(1, len(profile.projects[0].computations))
                self.assertEqual(1, len(profile.projects[1].computations))
                self.assertEqual(data_item0, list(profile.projects[0].computations[0].input_items)[0])
                self.assertEqual(data_item1, list(profile.projects[1].computations[0].input_items)[0])

    def test_data_item_in_computation_is_not_bound_to_another_project(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            item_uuid = uuid.uuid4()
            with contextlib.closing(document_model):
                data_item0 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid)
                document_model.append_data_item(data_item0, project=profile.projects[0])
                display_item0 = document_model.get_display_item_for_data_item(data_item0)
                document_model.get_invert_new(display_item0)
                data_item1 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid)
                document_model.append_data_item(data_item1, project=profile.projects[1])
                display_item1 = document_model.get_display_item_for_data_item(data_item1)
                document_model.get_invert_new(display_item1)
                document_model.recompute_all()
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(profile.projects[0].data_items))
                self.assertEqual(2, len(profile.projects[1].data_items))
                self.assertEqual(1, len(profile.projects[0].computations))
                self.assertEqual(1, len(profile.projects[1].computations))
                self.assertEqual(data_item0, list(profile.projects[0].computations[0].input_items)[0])
                self.assertEqual(data_item1, list(profile.projects[1].computations[0].input_items)[0])
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            data_item0 = document_model.data_items[0]
            data_item1 = document_model.data_items[2]
            with contextlib.closing(document_model):
                self.assertEqual(4, len(document_model.data_items))
                self.assertEqual(2, len(profile.projects[0].data_items))
                self.assertEqual(2, len(profile.projects[1].data_items))
                self.assertEqual(1, len(profile.projects[0].computations))
                self.assertEqual(1, len(profile.projects[1].computations))
                self.assertEqual(data_item0, list(profile.projects[0].computations[0].input_items)[0])
                self.assertEqual(data_item1, list(profile.projects[1].computations[0].input_items)[0])

    def test_project_reloads_with_same_uuid(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                project_uuid = document_model.projects[0].uuid
                project_specifier = document_model.projects[0].item_specifier
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                self.assertEqual(project_uuid, document_model.projects[0].uuid)
                self.assertEqual(document_model.projects[0], profile.persistent_object_context.get_registered_object(project_specifier))

    def test_memory_project_opens_with_same_uuid(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                project_uuid = document_model.projects[0].uuid
                project_specifier = document_model.projects[0].item_specifier
            profile_context.reset_profile()
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                TestContext.add_project_memory(profile, project_uuid)
                self.assertEqual(project_uuid, document_model.projects[1].uuid)
                self.assertEqual(document_model.projects[1], profile.persistent_object_context.get_registered_object(project_specifier))

    def test_memory_project_with_wrong_uuid_does_not_load(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                project_uuid = document_model.projects[0].uuid
            profile_context.project_properties["uuid"] = str(uuid.uuid4())
            profile_context.reset_profile()
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                TestContext.add_project_memory(profile, project_uuid)
                self.assertEqual(2, len(profile.project_references))
                self.assertEqual(1, len(document_model.projects))

    def test_partial_uuid_is_not_bound_to_items_in_another_project(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            item_uuid_0_src = uuid.uuid4()
            item_uuid_0_dst = uuid.uuid4()
            item_uuid_1_src = uuid.uuid4()
            item_uuid_1_dst = uuid.uuid4()
            with contextlib.closing(document_model):
                data_item_0_src = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid_0_src)
                data_item_0_dst = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid_0_dst)
                data_item_1_src = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid_1_src)
                data_item_1_dst = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid_1_dst)
                document_model.append_data_item(data_item_0_src, project=profile.projects[0])
                document_model.append_data_item(data_item_0_dst, project=profile.projects[0])
                data_item_0_dst.source = data_item_0_src
                document_model.append_data_item(data_item_1_src, project=profile.projects[1])
                document_model.append_data_item(data_item_1_dst, project=profile.projects[1])
                data_item_1_dst.source = data_item_1_src
            # make the source in first project point to the data item in the other project. should not load.
            list(profile_context.x_data_properties_map.values())[0][str(item_uuid_0_dst)]["source_uuid"] = str(item_uuid_1_dst)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(4, len(document_model.data_items))
                self.assertIsNone(document_model.data_items[1].source)
                self.assertEqual(document_model.data_items[3].source.project, document_model.data_items[3].project)

    def test_computation_works_with_inputs_in_different_projects(self):
        # create two data items in different projects. select the two items in the data panel
        # and create a computation from the two inputs. compute and make sure no errors occur.
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_controller):
                data1 = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
                data2 = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
                data_item1 = DataItem.DataItem(data1)
                data_item2 = DataItem.DataItem(data2)
                document_model.append_data_item(data_item1, project=document_model.projects[0])
                document_model.append_data_item(data_item2, project=document_model.projects[1])
                display_item1 = document_model.get_display_item_for_data_item(data_item1)
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                document_controller.select_display_items_in_data_panel([display_item1, display_item2])
                self.assertEqual(2, len(document_model.data_items))
                document_controller.perform_action("processing.cross_correlate")
                self.assertEqual(3, len(document_model.data_items))
                document_model.recompute_all()
                self.assertIsNone(document_model.computations[0].error_text)

    def test_adding_same_project_raises_error_during_append(self):
        # create two data items in different projects. select the two items in the data panel
        # and create a computation from the two inputs. compute and make sure no errors occur.
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_controller):
                project_reference = TestContext.MemoryProjectReference()
                project_reference.project_uuid = document_model.projects[0].uuid
                with self.assertRaises(Exception):
                    profile.append_project_reference(project_reference)

    # do not import same project (by uuid) twice
