"""Deployment checks without printing configuration values."""
import os


def validate(environ):
    if len(environ.get('ACTION_GUARD_API_TOKEN', '')) < 32:
        raise ValueError('ACTION_GUARD_API_TOKEN precisa de pelo menos 32 caracteres aleatorios.')
    if environ.get('ACTION_GUARD_DEMO_MODE', '').lower() not in {'true', 'false'}:
        raise ValueError('Defina ACTION_GUARD_DEMO_MODE como true ou false.')


if __name__ == '__main__':
    try:
        validate(os.environ)
    except ValueError as exc:
        raise SystemExit(str(exc))
    os.execvp('uvicorn', ['uvicorn', 'web.app.main:app', '--host', '0.0.0.0', '--port', '8000', '--workers', '1'])
