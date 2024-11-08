# Jira to Yandex Tracker

`jira-to-yatracker` — это инструмент для миграции задач из Jira в Yandex Tracker, включая все комментарии и вложения. Этот проект разработан для упрощения процесса переноса данных между двумя системами управления задачами, обеспечивая плавный переход и минимизацию потерь информации.

## Функции

- Миграция задач с полями, которые можно настроить через INI-файл сопоставления.
- Перенос комментариев и вложений к задачам.
- Перенос связей с другими задачами и статусов.
- Конфигурация через YAML-файл для удобного указания параметров подключения к Jira и Yandex Tracker.
- Выбор диапазона переносимых задач посредством редактирования .env файла.

## Использование

Для запуска инструмента используйте следующую команду:

```bash
docker-compose up --build
```

**Важно!** Миграция производится с сохранением номеров задач. К примеру: при миграции задачи IT-64 из Jira, проверяется существование задачи с таким номеров в Yandex Tracker, и, если такая задача нашлась, — производится **перезапись её полей** новыми значениями.

### Режимы работы

Перенос может осуществляться в двух режимах:

- `converge_issues` — одновременно переносит задачи и устанавливает связи между задачами
- `establish_links_only` — устанавливает связи между задачами

Выбор режима запуска производится через параметр `JIRA2YATRACKER_COMMAND` в файле `example/.env`.

### Конфигурирование

Параметры запуска задаются в файле `example/.env`, который может содержать следующие поля:

```
JIRA2YATRACKER_COMMAND=<режим работы, см. раздел выше>
JIRA2YATRACKER_STARTED_TASK_NUMBER=<числовой начальный номер задачи>
JIRA2YATRACKER_FINISH_TASK_NUMBER=<числовой конечный номер задачи>
```

Для задания параметров подключения и сопоставления — отредактируйте соответствующие поля у файлов в директории `example`.

#### Пример конфигурационного файла (`config.yaml`)

```yaml
project_and_queue_key: "<common-prefix-for-issues>"
final_status_for_wip_issue: "<status-for-wip-issue>Meta"
connection:
  jira:
    url: "https://<your-jira-instance>.atlassian.net"
    username: "<user-name>"
    api_token: "<generated-jira-token>"
  yandex_tracker:
    token: "<generated-yandex-tracker-token>"
    org_id: "<id-of-organization>"
    account_type: "<cloud-or-ya360>"
```

#### Пример файла сопоставления (`mapping.ini`)

```ini
; Сопоставление сущностей из Jira сущностям в Yandex Tracker
; ключи в отличии от значений не чувствительны к регистру (кроме содержимого custom_fields)

[users]
<username-in-jira> = <username-in-yandex-tracker>

; приоритеты задач
[priorities]
highest = blocker
high = critical
medium = normal
low = minor
lowest = trivial

; типы задач
[types]
задача = task
история = story
баг = bug
эпик = epic
подзадача = subtask

; статусы задач
[statuses]
backlog = backlogMeta
in progress = inProgressMeta
done = closedMeta

; связи между задачами 
[relationships]
blocks = is dependent by
relates to = relates
duplicates = duplicates
causes = depends on
clones = duplicates
subtask = is parent task for
epic = is epic of

; дополнительные поля
; обращение к вложенным полям производится через точку
[custom_fields]
labels = tags
components.name = components
```

## Примечание

Список рекомендаций и особенностей при переносе задач:

- Требуется остановить процесс (Ctrl-C) — нужно перезалить ту задачу, на которой была остановка.
- При падении скрипта с ошибкой — следующий запуск можно начать с упавшей задачи, указав ее в качестве стартовой в `JIRA2YATRACKER_STARTED_TASK_NUMBER`.
- Если задач много — лучше лить батчами, задав `JIRA2YATRACKER_FINISH_TASK_NUMBER`.
- Для заполнения `custom_fields` — ключи можно задать, посмотрев результат вызова Jira API `GET /rest/api/2/issue/{issueIdOrKey}`.
- Советую настроить рабочий процесс в Yandex Tracker с возможность перехода из любого статуса в любой другой.

## Лицензия

Этот проект лицензирован под лицензией MIT. Пожалуйста, смотрите файл `LICENSE` для подробностей.