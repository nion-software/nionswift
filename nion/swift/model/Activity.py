from __future__ import annotations

# standard libraries
# None

# third party libraries
# None

# local libraries
from nion.utils import Event
from nion.utils import Observable


class Activity(Observable.Observable):
    def __init__(self, activity_id: str, title: str) -> None:
        super().__init__()
        self.activity_id = activity_id
        self.title = title

    @property
    def displayed_title(self) -> str:
        return self.title


activity_appended_event = Event.Event()
activity_finished_event = Event.Event()


def append_activity(activity: Activity) -> None:
    # in order to be able to be called on other threads, just send an event. the activity panel will listen.
    activity_appended_event.fire(activity)


def activity_finished(activity: Activity) -> None:
    # in order to be able to be called on other threads, just send an event. the activity panel will listen.
    activity_finished_event.fire(activity)
