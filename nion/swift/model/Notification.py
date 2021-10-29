# reference https://developer.android.com/training/notify-user/build-notification

from __future__ import annotations

# standard libraries
# None

# third party libraries
# None

# local libraries
import typing

from nion.utils import Event
from nion.utils import Observable
from nion.utils import Registry


class Notification(Observable.Observable):
    # click action
    # dismiss
    # auto close

    def __init__(self, notification_type_id: str, task_name: str, title: str, text: str) -> None:
        super().__init__()
        self.dismiss_event = Event.Event()
        self.notification_type_id = notification_type_id
        self.__task_name = task_name
        self.__title = title
        self.__text = text

    @property
    def task_name(self) -> str:
        return self.__task_name

    @task_name.setter
    def task_name(self, value: str) -> None:
        self.__task_name = value
        self.notify_property_changed("task_name")

    @property
    def title(self) -> str:
        return self.__title

    @title.setter
    def title(self, value: str) -> None:
        self.__title = value
        self.notify_property_changed("title")

    @property
    def text(self) -> str:
        return self.__text

    @text.setter
    def text(self, value: str) -> None:
        self.__text = value
        self.notify_property_changed("text")

    def dismiss(self) -> None:
        self.dismiss_event.fire()


class NotificationSourceLike(typing.Protocol):
    notify_event: Event.Event
    notifications: typing.Sequence[Notification]


class NotificationSource(NotificationSourceLike):
    def __init__(self) -> None:
        self.notify_event = Event.Event()
        self.notifications: typing.List[Notification] = list()

    def notify(self, notification: Notification) -> None:
        self.notifications.append(notification)
        self.notify_event.fire(notification)


_notification_source = NotificationSource()


def notify(notification: Notification) -> None:
    _notification_source.notify(notification)


Registry.register_component(_notification_source, {"notification-source"})
