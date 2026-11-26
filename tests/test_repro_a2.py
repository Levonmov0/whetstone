from whetstone.platform.daemon import is_running


def test_a_pid_owned_by_another_user_does_not_crash() -> None:
    # pid 1 (launchd/init) is root's; signalling it as a normal user raises PermissionError.
    assert is_running(1) is True
