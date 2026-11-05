"""Server-owned execution policy; unknown values fail closed."""
import os


def demo_mode():
    return os.environ.get('ACTION_GUARD_DEMO_MODE', 'false').strip().lower() not in {'0', 'false'}


def execution_enabled():
    return not demo_mode()
