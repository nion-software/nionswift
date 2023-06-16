from __future__ import annotations

# standard libraries
import asyncio
import gettext
import threading
import typing

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import Activity
from nion.ui import Declarative
from nion.utils import Model
from nion.utils import ListModel
from nion.utils import Process
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController

_ = gettext.gettext


class ActivityHandler(Declarative.Handler):
    """Declarative component handler for a section in a multiple acquire method component."""

    def __init__(self, activity: Activity.Activity) -> None:
        super().__init__()
        self.activity = activity
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_row(
            u.create_label(text="@binding(activity.displayed_title)", word_wrap=True, width=296),
            u.create_stretch(),
            spacing=8
        )


class ActivityComponentFactory(typing.Protocol):
    def make_activity_component(self, activity: Activity.Activity) -> typing.Optional[Declarative.HandlerLike]: ...


class ActivityController(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController) -> None:
        super().__init__()

        # the activities list model is used for the UI, but is not threadsafe.
        # the pending activities is used for items that might be waiting to be added
        # to the list model.
        self.__pending_activities_lock = threading.RLock()
        self.__pending_append_activities: typing.List[Activity.Activity] = list()
        self.__pending_finished_activities: typing.List[Activity.Activity] = list()

        activities = ListModel.ListModel[Activity.Activity]()
        stack_index = Model.PropertyModel[int](0)

        async def maintain_activities() -> None:
            while True:
                await asyncio.sleep(0.2)
                with Process.audit("maintain_activities"):
                    with self.__pending_activities_lock:
                        for activity in self.__pending_append_activities:
                            activities.append_item(activity)
                        for activity in reversed(self.__pending_finished_activities):
                            activities.remove_item(activities.items.index(activity))
                        self.__pending_append_activities.clear()
                        self.__pending_finished_activities.clear()

        self.__maintain_task = document_controller.event_loop.create_task(maintain_activities())

        def activity_appended(activity: Activity.Activity) -> None:
            with self.__pending_activities_lock:
                self.__pending_append_activities.append(activity)

        def activity_finished(activity: Activity.Activity) -> None:
            with self.__pending_activities_lock:
                if activity in self.__pending_append_activities:
                    self.__pending_append_activities.remove(activity)
                else:
                    self.__pending_finished_activities.append(activity)

        self.__activity_appended_listener = Activity.activity_appended_event.listen(activity_appended)
        self.__activity_finished_listener = Activity.activity_finished_event.listen(activity_finished)

        self.activities = activities
        self.stack_index = stack_index

        def activity_changed(key: str, value: Activity.Activity, index: int) -> None:
            stack_index.value = 1 if len(activities.items) > 0 else 0

        self.__activity_inserted_listener = self.activities.item_inserted_event.listen(activity_changed)
        self.__activity_removed_listener = self.activities.item_removed_event.listen(activity_changed)

        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(
            u.create_label(text=_("** Activity Panel is Beta **"), color="darkred", font="bold"),
            u.create_stack(
                u.create_column(
                    u.create_label(text=_("No activities.")),
                    u.create_stretch(),
                ),
                u.create_column(
                    u.create_column(items="activities.items", item_component_id="activity", spacing=6),
                    u.create_stretch(),
                ),
                current_index="@binding(stack_index.value)"
            ),
            u.create_stretch(),
            spacing=8,
            margin=8
        )

    def close(self) -> None:
        self.__activity_appended_listener = typing.cast(typing.Any, None)
        self.__activity_finished_listener = typing.cast(typing.Any, None)
        try:
            self.__maintain_task.cancel()
            self.__maintain_task.result()
        except Exception as e:
            pass
        super().close()

    def create_handler(self, component_id: str, container: typing.Any = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        # this is called to construct contained declarative component handlers within this handler.
        if component_id == "activity":
            assert container is not None
            assert item is not None
            activity = typing.cast(Activity.Activity, item)
            for component in Registry.get_components_by_type("activity-component-factory"):
                activity_handler = typing.cast(ActivityComponentFactory, component)
                activity_component = activity_handler.make_activity_component(activity)
                if activity_component:
                    return activity_component
            return ActivityHandler(activity)
        return None


class ActivityPanel(Panel.Panel):
    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: typing.Mapping[str, typing.Any]) -> None:
        super().__init__(document_controller, panel_id, _("Activity"))
        activity_controller = ActivityController(document_controller)
        self.widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, activity_controller)

"""
        async def later() -> None:
            await asyncio.sleep(3.0)
            drink = Activity.Activity("drink", "Drink")
            Activity.append_activity(drink)

            await asyncio.sleep(3.0)
            eat = XActivity("Eat")
            Activity.append_activity(eat)

            await asyncio.sleep(3.0)
            Activity.activity_finished(eat)

            await asyncio.sleep(3.0)
            Activity.activity_finished(drink)

        document_controller.event_loop.create_task(later())
"""

"""
class XActivity(Activity.Activity):
    def __init__(self, title: str) -> None:
        super().__init__("x-activity", title)


class XActivityHandler(Declarative.Handler):
    # Declarative component handler for a section in a multiple acquire method component.

    def __init__(self, activity: Activity.Activity) -> None:
        super().__init__()
        assert isinstance(activity, XActivity)
        self.activity = activity
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_row(
            u.create_label(text="X"),
            u.create_label(text="@binding(activity.title)"),
            u.create_stretch(),
            spacing=8
        )

    def close(self) -> None:
        pass


class XActivityComponentFactory(ActivityComponentFactory):
    def make_activity_component(self, activity: Activity.Activity) -> typing.Optional[Declarative.HandlerLike]:
        if activity.activity_id == "x-activity":
            return XActivityHandler(activity)
        return None


Registry.register_component(XActivityComponentFactory(), {"activity-component-factory"})
"""
