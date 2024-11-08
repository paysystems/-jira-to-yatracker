import configparser
import typing
from functools import cache

import yandex_tracker_client as yatracker_old

from .exceptions import Jira2YaTrackerError


@cache
def _get_all_users_from_yatracker(
    yatracker_client: yatracker_old.TrackerClient,
) -> typing.Dict[str, int]:
    users = yatracker_client.users.get_all()
    return {user.display: user.uid for user in users}


@cache
def _get_all_components_from_yatracker(
    yatracker_client: yatracker_old.TrackerClient,
) -> typing.Dict[str, int]:
    components = yatracker_client.components.get_all()
    return {component.name: component.id for component in components}


class Jira2YaTrackerFieldMapper:
    users: typing.Dict[str, str]
    priorities: typing.Dict[str, str]
    types: typing.Dict[str, str]
    statuses: typing.Dict[str, str]
    relationships: typing.Dict[str, str]
    custom_fields: typing.Dict[str, str]

    def __init__(self, mapping_file_path: str) -> None:
        self.users = {}
        self.priorities = {}
        self.types = {}
        self.statuses = {}
        self.relationships = {}
        self.custom_fields = {}
        self.__parse_ini_file(mapping_file_path)

    def __parse_ini_file(self, file_path: str) -> None:
        config = configparser.ConfigParser()
        config.optionxform = str  # type: ignore

        successfully_read_files = config.read(file_path, encoding="utf-8")

        if not successfully_read_files:
            raise FileNotFoundError(f"Can't read mapping file: '{file_path}'")

        for section in config.sections():
            for key, value in config.items(section):
                try:
                    key_of_dict = key if section == "custom_fields" else key.lower()
                    getattr(self, section)[key_of_dict] = value
                except AttributeError as e:
                    raise ValueError(f"Unknown section: {section}") from e

    def __get_value_from_attr(self, section_name: str, key: str) -> str:
        section_dict: typing.Optional[typing.Dict[str, str]] = getattr(
            self, section_name, None
        )
        if section_dict is None:
            raise ValueError(f"Unknown section: {section_name}")

        key_of_dict = key if section_name == "custom_fields" else key.lower()
        yt_issue_field = section_dict.get(key_of_dict)

        if yt_issue_field is None:
            raise KeyError(
                f"Failed to find key '{key_of_dict}' in section '{section_name}'"
            )

        return yt_issue_field

    def jira_issue_type_to_yt_issue_type(self, issue_type: str) -> str:
        return self.__get_value_from_attr("types", issue_type)

    def jira_issue_priority_to_yt_issue_priority(self, issue_priority: str) -> str:
        return self.__get_value_from_attr("priorities", issue_priority)

    def jira_user_to_yt_user_id(
        self, user_object: typing.Any, yt_client: yatracker_old.TrackerClient
    ) -> typing.Optional[int]:
        if not user_object:
            return None

        if not hasattr(user_object, "displayName"):
            return None

        source_jira_username = self.__get_value_from_attr(
            "users", user_object.displayName
        )

        destination_yt_user_id = _get_all_users_from_yatracker(yt_client).get(
            source_jira_username
        )

        if destination_yt_user_id is None:
            raise Jira2YaTrackerError(
                f"Unknown Yandex Tracker user: {source_jira_username}"
            )

        return destination_yt_user_id

    def jira_issue_status_to_yt_issue_status(self, jira_issue_status: str) -> str:
        return self.__get_value_from_attr("statuses", jira_issue_status)

    def jira_relationship_to_yt_relation(self, relationship: str) -> str:
        return self.__get_value_from_attr("relationships", relationship)

    def jira_additional_fields_to_yt_additional_fields(
        self,
        jira_fields: typing.Any,
        yt_client: yatracker_old.TrackerClient,
        yt_issue_fields: typing.Any,
    ) -> typing.Dict[str, typing.Any]:
        result = {}

        for key, value in self.custom_fields.items():
            target_field = jira_fields

            for part_of_key in key.split("."):
                if not isinstance(target_field, list):
                    target_field = getattr(target_field, part_of_key, None)
                    continue

                target_field = list(
                    filter(
                        lambda x: x is not None,
                        (getattr(item, part_of_key, None) for item in target_field),
                    )
                )

            if isinstance(target_field, list):
                source_yt_value = getattr(yt_issue_fields, value, [])

                if value == "components":
                    components = _get_all_components_from_yatracker(yt_client)
                    fields_to_add = [int(components[i]) for i in target_field]
                    fields_to_remove = [
                        int(x)
                        for x in [yt_component.id for yt_component in source_yt_value]
                        if int(x) not in fields_to_add
                    ]
                else:
                    fields_to_add = target_field
                    fields_to_remove = [
                        x for x in source_yt_value if x not in fields_to_add
                    ]

                # Из `fields_to_add` можно выкинуть значения, если они уже присутствуют в `source_yt_value`
                # этого не делается, чтобы видеть устанавливаемые значения в логах
                if fields_to_add or fields_to_remove:
                    result[value] = {"add": fields_to_add, "remove": fields_to_remove}

                continue

            if target_field is not None:
                result[value] = target_field

        return result
