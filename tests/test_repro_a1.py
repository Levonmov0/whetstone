import subprocess
import sys

from whetstone.platform.daemon import is_running, stop

IGNORES_SIGTERM = "import signal, sys, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('ready', flush=True)\ntime.sleep(60)\n"


def test_stop_returns_only_once_the_process_is_gone() -> None:
    process = subprocess.Popen([sys.executable, "-c", IGNORES_SIGTERM], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout and process.stdout.readline() == "ready\n"

        stop(process.pid, timeout=0.5)

        assert not is_running(process.pid), "stop() returned while the process still runs"
    finally:
        process.kill()
        process.wait()
