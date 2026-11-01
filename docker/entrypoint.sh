#!/bin/sh
# Serve the assistant in the browser behind a username/password prompt. Each browser tab gets
# its own assistant process, with no shell underneath: typing `exit` ends only that tab's
# session, and the page offers to reconnect. All sessions share the data in /data.
set -eu

: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"
: "${ACCESS_USER:?ACCESS_USER must be set}"
: "${ACCESS_PASSWORD:?ACCESS_PASSWORD must be set}"

exec ttyd \
    --port 7681 \
    --writable \
    --credential "$ACCESS_USER:$ACCESS_PASSWORD" \
    --client-option titleFixed="HarborDesk assistant" \
    --client-option fontSize=15 \
    --client-option disableLeaveAlert=true \
    startup-assistant --data-dir /data
