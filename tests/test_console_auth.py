from old_sun_mcp.console_auth import GitHubIdentity, identity_allowed


def test_identity_pin_requires_login_and_immutable_id() -> None:
    ryan = GitHubIdentity("ryancnelson", 12345)
    assert identity_allowed(ryan, login="ryancnelson", user_id=12345)
    assert not identity_allowed(ryan, login="ryancnelson", user_id=99999)
    assert not identity_allowed(ryan, login="someone-else", user_id=12345)
