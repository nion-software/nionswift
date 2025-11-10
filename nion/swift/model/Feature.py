from __future__ import annotations

import json
import typing

from nion.swift.model import Utility
from nion.utils import Event
from nion.utils import Observable


class Feature(Observable.Observable):
    def __init__(self, feature_id: str, description: str, enabled: bool = False) -> None:
        super().__init__()
        self.feature_id = feature_id
        self.description = description
        self.__enabled = enabled

    @property
    def enabled(self) -> bool:
        return self.__enabled

    @enabled.setter
    def enabled(self, enabled: bool) -> None:
        if self.__enabled != enabled:
            self.__enabled = enabled
            self.notify_property_changed("enabled")


class FeatureManager(Observable.Observable, metaclass=Utility.Singleton):
    def __init__(self) -> None:
        super().__init__()
        self.__features = list[Feature]()
        self.__feature_listeners = list[Event.EventListener]()
        self.__enabled_features = dict[str, bool]()

    @property
    def enabled_feature_str(self) -> str:
        return json.dumps({feature.feature_id: feature.enabled for feature in self.features})

    @enabled_feature_str.setter
    def enabled_feature_str(self, enabled_features_str: str) -> None:
        try:
            self.__enabled_features = json.loads(enabled_features_str)
            for enabled_feature in self.__enabled_features.keys():
                feature = self.get_feature(enabled_feature)
                if feature:
                    feature.enabled = self.__enabled_features[enabled_feature]
        except Exception as e:
            pass  # don't fail to launch due to bad json

    @property
    def features(self) -> typing.Sequence[Feature]:
        return list(self.__features)

    def add_feature(self, feature: Feature) -> None:
        assert feature.feature_id not in [f.feature_id for f in self.__features]
        # set initial enabled state from saved state, in case feature is registered after enabled_feature_str has been set
        if feature.feature_id in self.__enabled_features:
            feature.enabled = self.__enabled_features[feature.feature_id]
        self.__features.append(feature)
        self.__feature_listeners.append(feature.property_changed_event.listen(self.__feature_property_changed))

    def __feature_property_changed(self, property_name: str) -> None:
        if property_name == "enabled":
            self.notify_property_changed("enabled_feature_str")

    def get_feature(self, feature_id: str) -> typing.Optional[Feature]:
        for feature in self.__features:
            if feature.feature_id == feature_id:
                return feature
        return None

    def is_feature_enabled(self, feature_id: str) -> bool:
        feature = self.get_feature(feature_id)
        return feature.enabled if feature else False

