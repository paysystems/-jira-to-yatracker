import argparse
import enum
import os
import typing


class CommandEnum(enum.IntEnum):
    CONVERGE_ISSUES = 1
    ESTABLISH_LINKS_ONLY = 2

    def __str__(self) -> str:
        return self.name.lower()

    def __repr__(self) -> str:
        return str(self)

    @staticmethod
    def argparse(s: str) -> typing.Any:
        try:
            return CommandEnum[s.upper()]
        except KeyError:
            return s


def parse_command_line_arguments() -> argparse.Namespace:
    argument_parser = argparse.ArgumentParser(
        prog="jira-to-yatracker",
        description="Migrate Jira issues to Yandex Tracker with all comments and attachments",
    )

    argument_parser.add_argument(
        "command",
        type=CommandEnum.argparse,
        choices=list(CommandEnum),
        help="command to execute for migration",
    )

    argument_parser.add_argument(
        "--config",
        type=str,
        default=os.getenv("JIRA2YATRACKER_CONFIG_FILE", "config.yaml"),
        help="path to config file with connection parameters (env JIRA2YATRACKER_CONFIG_FILE)",
    )

    argument_parser.add_argument(
        "--mapping",
        type=str,
        default=os.getenv("JIRA2YATRACKER_MAPPING_FILE", "mapping.ini"),
        help="path to mapping file with Jira to Yandex Tracker field mapping (env JIRA2YATRACKER_MAPPING_FILE)",
    )

    argument_parser.add_argument(
        "--started-task-number",
        type=int,
        default=os.getenv("JIRA2YATRACKER_STARTED_TASK_NUMBER", "1"),
        help="task number for started migration (env JIRA2YATRACKER_STARTED_TASK_NUMBER)",
    )

    argument_parser.add_argument(
        "--finish-task-number",
        type=int,
        default=os.getenv("JIRA2YATRACKER_FINISH_TASK_NUMBER", "-1"),
        help="task number for finish migration (env JIRA2YATRACKER_FINISH_TASK_NUMBER)",
    )

    return argument_parser.parse_args()
