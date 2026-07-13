import pytest
from command_parser import parse_command

def test_parse_command_power():
    assert parse_command("shutdown computer") == ("shutdown", {})
    assert parse_command("restart system") == ("restart", {})
    assert parse_command("lock screen") == ("lock", {})
    assert parse_command("log off") == ("logoff", {})

def test_parse_command_clipboard():
    assert parse_command("copy that") == ("clipboard", {"action": "copy"})
    assert parse_command("paste it") == ("clipboard", {"action": "paste"})

def test_parse_command_open_app():
    assert parse_command("open firefox") == ("open_app", {"app": "firefox"})
    assert parse_command("launch google chrome please") == ("open_app", {"app": "google chrome"})
    assert parse_command("start terminal") == ("open_app", {"app": "terminal"})
    assert parse_command("run code") == ("open_app", {"app": "code"})

def test_parse_command_open_location():
    assert parse_command("open downloads folder") == ("open_location", {"path": "~/Downloads"})
    assert parse_command("go to home") == ("open_location", {"path": "~"})

def test_parse_command_run_command():
    assert parse_command("run terminal htop") == ("run_command", {"command": "htop"})
    assert parse_command("execute command ls -la") == ("run_command", {"command": "ls -la"})

def test_parse_command_close_app():
    assert parse_command("close firefox") == ("close_app", {"app": "firefox"})
    assert parse_command("kill terminal") == ("close_app", {"app": "terminal"})

def test_parse_command_kill_process():
    assert parse_command("kill process python") == ("kill_process", {"name": "python"})

def test_parse_command_weather():
    assert parse_command("what is the weather") == ("weather", {})

def test_parse_command_time_date():
    assert parse_command("what time is it") == ("time", {})
    assert parse_command("what's the date") == ("date", {})

def test_parse_command_system():
    assert parse_command("system info") == ("system_info", {})
    assert parse_command("cpu usage") == ("system_stats", {})

def test_parse_command_web_search():
    assert parse_command("search for python tutorials") == ("web_search", {"query": "python tutorials"})
    assert parse_command("google linux commands") == ("web_search", {"query": "linux commands"})

def test_parse_command_media():
    assert parse_command("play lofi beats") == ("play_media", {"query": "lofi beats"})

def test_parse_command_file_operations():
    assert parse_command("find document.pdf") == ("find_file", {"filename": "document.pdf"})
    assert parse_command("create folder new_project") == ("create_item", {"name": "new_project", "type": "folder"})
    assert parse_command("create file notes.txt") == ("create_item", {"name": "notes.txt", "type": "file"})

def test_parse_command_volume():
    assert parse_command("volume up") == ("volume", {"action": "up"})
    assert parse_command("mute sound") == ("volume", {"action": "mute"})

def test_parse_command_calculate():
    assert parse_command("calculate 5 + 5") == ("calculate", {"expression": "5 + 5"})

def test_parse_command_timers():
    assert parse_command("set a timer for 5 minutes") == ("set_timer", {"text": "timer", "seconds": "300"})
    assert parse_command("remind me in 1 hour to sleep") == ("set_reminder", {"text": "sleep", "seconds": "3600"})

def test_parse_command_chat():
    assert parse_command("hello world") == ("chat", {"text": "hello world"})
    assert parse_command("who are you?") == ("chat", {"text": "who are you?"})
