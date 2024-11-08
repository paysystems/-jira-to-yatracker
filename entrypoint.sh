#!/bin/bash

set -eu

python -m src "${JIRA2YATRACKER_COMMAND}" "$@"