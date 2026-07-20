from .cli import cli, emit_failure_signal

try:
    cli(standalone_mode=False)
except Exception as e:
    emit_failure_signal(e)
    raise SystemExit(1) from e
