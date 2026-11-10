from jarvis.core.permissions import PermissionGate
from jarvis.core.tools import AUTO, BLOCKED, CONFIRM


def tier(gate, registry, ctx, name, args):
    return gate.decide(registry.get(name), args, ctx).tier


def test_reading_is_automatic(settings, registry, ctx):
    gate = PermissionGate(settings)
    (ctx.workspace / "a.txt").write_text("hi")
    assert tier(gate, registry, ctx, "read_file", {"path": "a.txt"}) == AUTO
    assert tier(gate, registry, ctx, "list_dir", {}) == AUTO
    assert tier(gate, registry, ctx, "search_files", {"name": "*.txt"}) == AUTO


def test_reading_sensitive_paths_needs_confirmation(settings, registry, ctx, tmp_path):
    gate = PermissionGate(settings)
    for p in [".ssh/id_rsa", "project/.env", "certs/server.pem", "AppData/Local/Google/Chrome/User Data/Default/Cookies"]:
        assert tier(gate, registry, ctx, "read_file", {"path": str(tmp_path / p)}) == CONFIRM, p
    assert tier(gate, registry, ctx, "list_dir", {"path": str(tmp_path / ".ssh")}) == CONFIRM
    # Windows paths differ only in case from the patterns.
    assert tier(gate, registry, ctx, "read_file", {"path": str(tmp_path / "appdata/local/google/chrome/user data/x")}) == CONFIRM


def test_new_file_in_workspace_is_automatic_overwrite_is_not(settings, registry, ctx):
    gate = PermissionGate(settings)
    args = {"path": "notes.txt", "content": "x"}
    assert tier(gate, registry, ctx, "write_file", args) == AUTO
    (ctx.workspace / "notes.txt").write_text("old")
    d = gate.decide(registry.get("write_file"), args, ctx)
    assert d.tier == CONFIRM
    assert "Overwrite" in d.description and "-old" in d.description and "+x" in d.description


def test_writing_outside_workspace_needs_confirmation(settings, registry, ctx, tmp_path):
    gate = PermissionGate(settings)
    assert tier(gate, registry, ctx, "write_file", {"path": str(tmp_path / "out.txt"), "content": "x"}) == CONFIRM
    assert tier(gate, registry, ctx, "write_file", {"path": "../escape.txt", "content": "x"}) == CONFIRM
    assert tier(gate, registry, ctx, "make_dir", {"path": str(tmp_path / "newdir")}) == CONFIRM
    assert tier(gate, registry, ctx, "move_file", {"source": "a", "destination": str(tmp_path / "b")}) == CONFIRM


def test_symlink_cannot_disguise_an_outside_path(settings, registry, ctx, tmp_path):
    gate = PermissionGate(settings)
    outside = tmp_path / "outside"
    outside.mkdir()
    (ctx.workspace / "link").symlink_to(outside, target_is_directory=True)
    assert tier(gate, registry, ctx, "write_file", {"path": "link/x.txt", "content": "x"}) == CONFIRM


def test_delete_and_commands_always_confirm(settings, registry, ctx):
    gate = PermissionGate(settings)
    assert tier(gate, registry, ctx, "delete_file", {"path": "a.txt"}) == CONFIRM
    assert tier(gate, registry, ctx, "run_command", {"command": "echo hi"}) == CONFIRM
    assert tier(gate, registry, ctx, "run_python", {"code": "print(1)"}) == CONFIRM


def test_blocked_patterns(settings, registry, ctx):
    gate = PermissionGate(settings)
    for cmd in [
        "netsh advfirewall set allprofiles state off",
        "Set-MpPreference -DisableRealtimeMonitoring $true",
        "powershell Set-ExecutionPolicy Unrestricted",
        "net user hacker P@ss /add",
        "format C: /q",
        "rm -rf /",
        "sudo ufw disable",
    ]:
        d = gate.decide(registry.get("run_command"), {"command": cmd}, ctx)
        assert d.tier == BLOCKED, cmd
    code = "import os; os.system('netsh advfirewall set allprofiles state off')"
    assert tier(gate, registry, ctx, "run_python", {"code": code}) == BLOCKED
    # A blocked script stays blocked when run from a file.
    (ctx.workspace / "bad.py").write_text(code)
    assert tier(gate, registry, ctx, "run_python", {"path": "bad.py"}) == BLOCKED
    # Ordinary commands are not caught.
    assert tier(gate, registry, ctx, "run_command", {"command": "git status"}) == CONFIRM
    assert tier(gate, registry, ctx, "run_command", {"command": "rm -rf ./build"}) == CONFIRM


def test_settings_can_tighten_and_block(settings, registry, ctx):
    settings.tool_tiers["read_file"] = "confirm"
    settings.tool_tiers["run_command"] = "blocked"
    gate = PermissionGate(settings)
    assert tier(gate, registry, ctx, "read_file", {"path": "a.txt"}) == CONFIRM
    assert tier(gate, registry, ctx, "run_command", {"command": "echo"}) == BLOCKED


def test_settings_cannot_loosen_a_risky_call(settings, registry, ctx, tmp_path):
    settings.tool_tiers["write_file"] = "auto"
    gate = PermissionGate(settings)
    assert tier(gate, registry, ctx, "write_file", {"path": str(tmp_path / "x"), "content": ""}) == CONFIRM


def test_typo_in_settings_fails_safe(settings, registry, ctx):
    settings.tool_tiers["read_file"] = "atuo"
    gate = PermissionGate(settings)
    assert tier(gate, registry, ctx, "read_file", {"path": "a.txt"}) == CONFIRM


def test_unlisted_tool_uses_default_tier(settings, registry, ctx):
    from jarvis.core.tools import Tool

    gate = PermissionGate(settings)
    t = Tool("mystery", "", {"type": "object"}, lambda a, c: "x")
    assert gate.decide(t, {}, ctx).tier == CONFIRM


def test_untrusted_content_escalates_later_actions(settings, registry, ctx):
    gate = PermissionGate(settings)
    args = {"path": "new.txt", "content": "x"}
    assert tier(gate, registry, ctx, "write_file", args) == AUTO
    gate.note_untrusted()
    assert tier(gate, registry, ctx, "write_file", args) == CONFIRM
    assert tier(gate, registry, ctx, "read_file", {"path": "new.txt"}) == AUTO  # reading stays automatic
    gate.new_request()
    assert tier(gate, registry, ctx, "write_file", args) == AUTO
