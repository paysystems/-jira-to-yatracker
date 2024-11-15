# pylint: disable=global-statement broad-exception-caught protected-access

import argparse
import asyncio
import json
import locale
import logging
import typing
from datetime import timedelta, timezone

import jira
import jira.resources
import yandex_tracker_client as yatracker_old
import yatracker
import yatracker.exceptions
import yatracker.tracker
import yatracker.tracker.base
import yatracker.types
from dateutil import parser
from jira2markdown import convert
from tenacity import retry, stop_after_attempt, wait_fixed, wait_random

from .cl_arguments import CommandEnum, parse_command_line_arguments
from .config_loader import YamlConfig
from .field_mapper import Jira2YaTrackerFieldMapper

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

for log_name, log_obj in logging.Logger.manager.loggerDict.items():
    if log_name != __name__:
        log_obj.disabled = True  # type: ignore

locale.setlocale(locale.LC_ALL, "ru_RU.utf8")

DEFAULT_ISSUE_TITLE = "[JIRA2YT] WIP"
COMMENT_TIMEZONE = timezone(timedelta(hours=3), "Moscow")
COMMENT_TIMEZONE_ALIAS = "МСК"

RETRY_KWARGS = {
    "stop": stop_after_attempt(3),
    "wait": wait_fixed(3) + wait_random(0, 5),
    "reraise": True,
}


jira_client: jira.JIRA
yt_client: yatracker.YaTracker
yt_old_client: yatracker_old.TrackerClient

jira_to_yt_mapper: Jira2YaTrackerFieldMapper
project_and_queue_key: str
final_status_for_wip_issue: str
starting_task: str
finish_task: typing.Optional[str]


@retry(**RETRY_KWARGS)  # type: ignore
async def migrate_all_comments(
    yt_issue: yatracker.types.FullIssue, comments: typing.List[jira.resources.Comment]
) -> None:
    for comment in await yt_issue.get_comments():
        await yt_client.delete_comment(yt_issue.id, comment.id)

    for index, comment in enumerate(comments):
        logger.info("Adding comment: %d", index + 1)
        final_comment = "%s создал %s\n\n%s" % (
            comment.author.displayName,
            parser.parse(comment.created)
            .astimezone(COMMENT_TIMEZONE)
            .strftime(f"%d %B %Y г. в %H:%M по {COMMENT_TIMEZONE_ALIAS}"),
            convert(comment.body),
        )
        await yt_client.post_comment(yt_issue.id, final_comment)


@retry(**RETRY_KWARGS)  # type: ignore
async def migrate_all_attachments(
    yt_issue: yatracker.types.FullIssue,
    attachments: typing.List[jira.resources.Attachment],
) -> None:
    for attachment in await yt_client.get_attachments(yt_issue.id):
        await yt_client.delete_attachment(yt_issue.id, attachment.id)

    for attachment in attachments:
        logger.info("Adding attachment: %s", attachment.filename)
        await yt_client.attach_file(yt_issue.id, attachment.get(), attachment.filename)


def logical_xor(a: typing.Any, b: typing.Any) -> bool:
    return bool(a) + bool(b) == 1


@retry(**RETRY_KWARGS)  # type: ignore
async def change_status(
    yt_issue: yatracker.types.FullIssue,
    *,
    jira_status_name: typing.Optional[str] = None,
    yt_status_name: typing.Optional[str] = None,
) -> None:
    if not logical_xor(jira_status_name, yt_status_name):
        raise ValueError("Either 'jira_status_name' or 'yt_status_name' must be set")

    if jira_status_name is not None:
        wanted_status = jira_to_yt_mapper.jira_issue_status_to_yt_issue_status(
            jira_status_name
        )
    else:
        wanted_status = yt_status_name  # type: ignore

    yt_issue_current_status = yt_issue.status.key + "Meta"

    if wanted_status == yt_issue_current_status:
        return

    if jira_status_name is not None:
        logger.info(
            "Updating status for Yandex Tracker issue '%s' from '%s' to '%s' because of Jira status is '%s'",
            yt_issue.key,
            yt_issue_current_status,
            wanted_status,
            jira_status_name,
        )
    else:
        logger.info(
            "Updating status for Yandex Tracker issue '%s' from '%s' to '%s'",
            yt_issue.key,
            yt_issue_current_status,
            wanted_status,
        )
    transitions = await yt_issue.get_transitions()
    transition = transitions[wanted_status]
    await transition.execute()


@retry(**RETRY_KWARGS)  # type: ignore
def link_yt_issues(
    first_issue_key: str, second_issue_key: str, type_of_relation: str
) -> None:
    relationship = jira_to_yt_mapper.jira_relationship_to_yt_relation(type_of_relation)
    error_messages = []

    try:
        yt_issue: yatracker_old.client.collections.Issues = yt_old_client.issues[
            first_issue_key
        ]

        yt_issue.links.create(
            issue=second_issue_key,
            relationship=relationship,
        )

        logger.info(
            "Linking Yandex Tracker issue '%s' with '%s' via '%s'",
            first_issue_key,
            second_issue_key,
            relationship,
        )
    except yatracker_old.client.collections.exceptions.UnprocessableEntity as e:
        # Для случаев, когда задачи уже связаны
        error_messages = e.error_messages
    except yatracker_old.client.collections.exceptions.NotFound as e:
        # Для случаев, когда задачи для связи не найдены
        error_messages = e.error_messages
    finally:
        if error_messages:
            logger.warning(
                "Linking Yandex Tracker issue '%s' with '%s' via '%s' caused exception: %s",
                first_issue_key,
                second_issue_key,
                relationship,
                error_messages,
            )


@retry(**RETRY_KWARGS)  # type: ignore
def delete_all_links(yt_issue_key: str) -> None:
    logger.info("Deleting all links for Yandex Tracker issue '%s'", yt_issue_key)
    ya_issue = yt_old_client.issues[yt_issue_key]
    for link in ya_issue.links:
        link.delete()


@retry(**RETRY_KWARGS)  # type: ignore
def get_all_jira_additional_linked_issues(
    jira_issue: jira.Issue,
) -> typing.Iterable[jira.Issue]:
    type_of_issue = jira_to_yt_mapper.jira_issue_type_to_yt_issue_type(
        jira_issue.fields.issuetype.name
    )

    if type_of_issue != "epic":
        return []

    # У эпика поле `subtasks` не заполняется, поэтому задачи получаем отдельным запросом
    jira_issues = list(
        jira_client.search_issues(
            f"key!={jira_issue.key} AND parentEpic IN ({jira_issue.key}) ORDER BY key ASC",
            maxResults=False,
        )
    )

    return jira_issues


def link_yt_issues_parent(
    first_issue_segment: typing.Any, second_issue_segment: typing.Any
) -> None:
    type_of_issue = jira_to_yt_mapper.jira_issue_type_to_yt_issue_type(
        first_issue_segment.fields.issuetype.name
    )

    if type_of_issue == "epic":
        link_yt_issues(first_issue_segment.key, second_issue_segment.key, "epic")
    else:
        link_yt_issues(first_issue_segment.key, second_issue_segment.key, "subtask")


def establish_links_between_issues(jira_issue: jira.Issue) -> None:
    parent_issue = getattr(jira_issue.fields, "parent", None)

    epic_issues = get_all_jira_additional_linked_issues(jira_issue)

    if not (
        jira_issue.fields.issuelinks
        or jira_issue.fields.subtasks
        or parent_issue
        or epic_issues
    ):
        return

    logger.info("Establishing links for Jira issue '%s'", jira_issue.key)

    for issue_link in jira_issue.fields.issuelinks:
        outward_issue = getattr(issue_link, "outwardIssue", None)
        inward_issue = getattr(issue_link, "inwardIssue", None)

        if outward_issue is not None:
            link_yt_issues(jira_issue.key, outward_issue.key, issue_link.type.outward)
        elif inward_issue is not None:
            # Меняем аргументы местами
            link_yt_issues(inward_issue.key, jira_issue.key, issue_link.type.outward)

    for subtask in jira_issue.fields.subtasks:
        link_yt_issues_parent(jira_issue, subtask)

    for child_task in epic_issues:
        link_yt_issues_parent(jira_issue, child_task)

    if parent_issue:
        # Меняем аргументы местами
        link_yt_issues_parent(parent_issue, jira_issue)


@retry(**RETRY_KWARGS)  # type: ignore
async def get_yt_issue_with_status_by_key_or_create_one(
    jira_issue: jira.Issue,
) -> typing.Optional[yatracker.types.FullIssue]:
    try:
        existing_issue = await yt_client.get_issue(jira_issue.key)
        await change_status(
            existing_issue, jira_status_name=jira_issue.fields.status.name
        )
        return existing_issue
    except yatracker.exceptions.YaTrackerError as e:
        status_code = json.loads(str(e))["statusCode"]
        if status_code != 404:
            raise

    ya_tmp_issue: typing.Optional[yatracker.types.FullIssue] = None
    try:
        ya_tmp_issue = await yt_client.create_issue(
            queue=project_and_queue_key,
            summary=DEFAULT_ISSUE_TITLE,
        )
    finally:
        if ya_tmp_issue is not None:
            logger.info("Created temporary issue with key: %s", ya_tmp_issue.key)
            await change_status(ya_tmp_issue, yt_status_name=final_status_for_wip_issue)


@retry(**RETRY_KWARGS)  # type: ignore
async def fill_common_fields(yt_issue_id: str, jira_issue: jira.Issue) -> None:
    logger.info(
        "Filling common fields for Yandex Tracker issue with id '%s'", yt_issue_id
    )
    await yt_client.edit_issue(
        issue_id=yt_issue_id,
        summary=jira_issue.fields.summary,
        type={
            "key": jira_to_yt_mapper.jira_issue_type_to_yt_issue_type(
                jira_issue.fields.issuetype.name
            )
        },
        priority={
            "key": jira_to_yt_mapper.jira_issue_priority_to_yt_issue_priority(
                jira_issue.fields.priority.name
            )
        },
        assignee=jira_to_yt_mapper.jira_user_to_yt_user_id(
            jira_issue.fields.assignee, yt_old_client
        ),
        created_by=jira_to_yt_mapper.jira_user_to_yt_user_id(
            jira_issue.fields.creator, yt_old_client
        ),
        description=(
            convert(jira_issue.fields.description)
            if jira_issue.fields.description
            else None
        ),
    )


@retry(**RETRY_KWARGS)  # type: ignore
def fill_additional_fields(yt_issue_id: str, jira_issue: jira.Issue) -> None:
    logger.info(
        "Filling additional fields for Yandex Tracker issue with id '%s'", yt_issue_id
    )
    yt_issue = yt_old_client.issues[yt_issue_id]
    additional_fields = (
        jira_to_yt_mapper.jira_additional_fields_to_yt_additional_fields(
            jira_fields=jira_issue.fields,
            yt_client=yt_old_client,
            yt_issue_fields=yt_issue,
        )
    )
    logger.debug("Additional fields: %s", additional_fields)
    yt_issue.update(**additional_fields)


async def create_yt_issue_and_migrate_fields(
    jira_issue: jira.Issue,
) -> yatracker.types.FullIssue:
    logger.info("Trying to find existing issue '%s' or create it", jira_issue.key)
    yt_issue = None
    while yt_issue is None:
        yt_issue = await get_yt_issue_with_status_by_key_or_create_one(jira_issue)
    await fill_common_fields(yt_issue.id, jira_issue)
    fill_additional_fields(yt_issue.id, jira_issue)
    await migrate_all_comments(yt_issue, jira_issue.fields.comment.comments)
    await migrate_all_attachments(yt_issue, jira_issue.fields.attachment)
    delete_all_links(yt_issue.key)
    establish_links_between_issues(jira_issue)
    return yt_issue


class TupleWithIssues(typing.NamedTuple):
    old_jira_issue: jira.Issue
    new_yt_issue: yatracker.types.FullIssue


async def converge_all_issues(
    jira_issues: typing.Iterable[jira.Issue],
) -> typing.AsyncIterable[TupleWithIssues]:
    for issue in jira_issues:
        logger.info("=> Creating Yandex Tracker issue from Jira issue '%s'", issue.key)
        try:
            yield TupleWithIssues(
                issue, await create_yt_issue_and_migrate_fields(issue)
            )
        except Exception as e:
            logger.error("Failed to create Yandex Tracker issue '%s': %s", issue.key, e)
            logger.debug("Source Jira issue data: %s", issue.raw)
            raise


def establish_links_for_all_issues(
    jira_issues: typing.Iterable[jira.Issue],
) -> None:
    for issue in jira_issues:
        establish_links_between_issues(issue)


def initialize_global_variables(parsed_args: argparse.Namespace) -> None:
    global jira_client, yt_client, yt_old_client
    global jira_to_yt_mapper, project_and_queue_key, final_status_for_wip_issue, starting_task, finish_task

    logger.info("Initializing global variables")

    config_file = YamlConfig(parsed_args.config)
    project_and_queue_key = config_file.get_field("project_and_queue_key")
    final_status_for_wip_issue = config_file.get_field("final_status_for_wip_issue")

    jira_to_yt_mapper = Jira2YaTrackerFieldMapper(parsed_args.mapping)

    starting_task = f"{project_and_queue_key}-{max(1, parsed_args.started_task_number)}"

    if parsed_args.finish_task_number > 0:
        finish_task = f"{project_and_queue_key}-{parsed_args.finish_task_number}"
    else:
        finish_task = None

    jira_client = jira.JIRA(
        server=config_file.get_field("connection.jira.url"),
        basic_auth=(
            config_file.get_field("connection.jira.username"),
            config_file.get_field("connection.jira.api_token"),
        ),
    )

    yt_client = yatracker.YaTracker(
        token=config_file.get_field("connection.yandex_tracker.token"),
        org_id=config_file.get_field("connection.yandex_tracker.org_id"),
    )

    yt_old_client = yatracker_old.TrackerClient(
        token=config_file.get_field("connection.yandex_tracker.token"),
        org_id=config_file.get_field("connection.yandex_tracker.org_id"),
        retries=0,
    )

    if config_file.get_field("connection.yandex_tracker.account_type", "") != "cloud":
        return

    # Hotfix для работы с Yandex Cloud Organization
    modern_client_headers = yt_client._client._headers
    modern_client_headers["X-Cloud-Org-ID"] = modern_client_headers["X-Org-Id"]
    del modern_client_headers["X-Org-Id"]

    old_client_headers = yt_old_client._connection.session.headers
    old_client_headers["X-Cloud-Org-ID"] = old_client_headers["X-Org-Id"]
    del old_client_headers["X-Org-Id"]


async def stage_converge_issues(jira_issues: typing.Iterable[jira.Issue]) -> None:
    logger.info(
        "[STAGE CONVERGE]: Converging all issues (including links establishing), starting..."
    )
    async for yt_issue in converge_all_issues(jira_issues):
        logger.info(
            "<= Created issue is Yandex Tracker '%s' from Jira issue '%s'",
            yt_issue.new_yt_issue.key,
            yt_issue.old_jira_issue.key,
        )
    logger.info("[STAGE CONVERGE]: Finished converging all issues")


def stage_establish_links_between_issues(
    jira_issues: typing.Iterable[jira.Issue],
) -> None:
    logger.info(
        "[STAGE ESTABLISH LINKS]: Establishing links between issues, starting..."
    )
    establish_links_for_all_issues(jira_issues)
    logger.info("[STAGE ESTABLISH LINKS]: Finished establishing links between issues")


@retry(**RETRY_KWARGS)  # type: ignore
def get_all_jira_issues() -> typing.Iterable[jira.Issue]:
    jira_issues = list(
        jira_client.search_issues(
            (
                f"key>={starting_task} ORDER BY key ASC"
                if finish_task is None
                else f"key>={starting_task} AND key<={finish_task} ORDER BY key ASC"
            ),
            maxResults=False,  # Для обхода лимита: https://jira.atlassian.com/browse/JRACLOUD-67570
        )
    )

    logger.info(
        "Got %d Jira issues starting with '%s'",
        len(jira_issues),
        starting_task,
    )

    return jira_issues


async def main():
    parsed_cl_args = parse_command_line_arguments()
    initialize_global_variables(parsed_cl_args)

    logger.info("Starting migration (please wait a few minutes)...")

    try:
        jira_issues = get_all_jira_issues()

        if parsed_cl_args.command == CommandEnum.CONVERGE_ISSUES:
            await stage_converge_issues(jira_issues)
        elif parsed_cl_args.command == CommandEnum.ESTABLISH_LINKS_ONLY:
            stage_establish_links_between_issues(jira_issues)
        else:
            raise ValueError(f"Unknown command: {parsed_cl_args.command}")

        logger.info("Migration finished")
    finally:
        logger.info("Shutting down gracefully")
        await yt_client.close()


asyncio.run(main())
