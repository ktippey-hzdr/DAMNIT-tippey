"""Compatibility constants used across DAMNIT.

Prefer the helpers in `damnit.site_config` for context-directory specific
values, because these constants are evaluated once at import time.
"""

from .site_config import (
    get_default_context_python,
    get_default_damnit_python,
    get_file_submit_topic,
    get_update_brokers,
    get_update_topic_template,
)

UPDATE_BROKERS = get_update_brokers()
UPDATE_TOPIC = get_update_topic_template()
FILE_SUBMIT_TOPIC = get_file_submit_topic()
DEFAULT_CONTEXT_PYTHON = get_default_context_python()
DEFAULT_DAMNIT_PYTHON = get_default_damnit_python()
