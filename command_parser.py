import re

def parse_command(text: str) -> tuple[str, dict]:
    """
    Parse natural language command into intent + parameters.
    Returns (intent, params_dict)
    """
    raw = text
    text = text.lower().strip().rstrip('.!?')

    # Strip prefixes
    prefixes = [
        'please ', 'could you ', 'can you ', 'would you ',
        'i need you to ', 'i want you to ', 'i need ', 'i want ',
        'hey pravaha ', 'hey ',
        'pravaha ', 'okay pravaha ',
    ]
    for p in prefixes:
        if text.startswith(p):
            text = text[len(p):]
            break
    text = text.strip()

    # ====== POWER COMMANDS ======
    if any(k in text for k in ['shutdown computer', 'shutdown system', 'power off',
                                'turn off computer', 'shutdown now', 'switch off']):
        return ("shutdown", {})
    if any(k in text for k in ['restart computer', 'restart system', 'reboot system',
                                'reboot computer', 'restart now']):
        return ("restart", {})
    if any(k in text for k in ['lock computer', 'lock system', 'lock workstation',
                                'lock screen', 'lock my computer']):
        return ("lock", {})
    if any(k in text for k in ['log off', 'logoff', 'sign out', 'signout']):
        return ("logoff", {})
    if any(k in text for k in ['hibernate', 'sleep computer', 'sleep system',
                                'go to sleep', 'put computer to sleep']):
        return ("hibernate", {})

    # Short form power commands
    if text.strip() in ['shutdown', 'shut down']:
        return ("shutdown", {})
    if text.strip() in ['restart', 'reboot']:
        return ("restart", {})
    if text.strip() in ['lock', 'lock screen']:
        return ("lock", {})

    # ====== CLIPBOARD ======
    if any(k in text for k in ['copy selection', 'copy that', 'copy to clipboard']):
        return ("clipboard", {"action": "copy"})
    if any(k in text for k in ['cut selection', 'cut that']):
        return ("clipboard", {"action": "cut"})
    if any(k in text for k in ['paste', 'paste from clipboard', 'paste it']):
        return ("clipboard", {"action": "paste"})
    if any(k in text for k in ['select all', 'select everything']):
        return ("clipboard", {"action": "select_all"})

    # ====== RUN COMMAND (check before open_match — requires "command"/"terminal" keyword) ======
    run_match = re.search(r'(?:run|execute)\s+(?:command\s+|terminal\s+)(.+?)$', text)
    if run_match:
        cmd = run_match.group(1).strip().rstrip('.')
        if cmd:
            return ("run_command", {"command": cmd})

    # ====== OPEN / LAUNCH / START ======
    open_match = re.search(r'(?:open|launch|start|run|fire\s*up|load\s*up)\s+(.+?)$', text)
    if open_match:
        target = open_match.group(1).strip().rstrip('.')
        target = re.sub(r'\s+(?:please|for\s+me|now|quickly|right\s+now)$', '', target).strip()

        # Strip articles
        for art in ['the ', 'my ', 'a ', 'an ']:
            if target.startswith(art):
                target = target[len(art):]
                break
        target = target.strip()

        if not target:
            return ("chat", {"text": raw})

        # Split on "and", "then", or comma to handle compound commands
        target = re.split(r'\s+(?:and|then)\s+|\s*,\s*', target)[0].strip()

        # Known location shortcuts (including compound names like "downloads folder")
        location_map = {
            'downloads': '~/Downloads',
            'download': '~/Downloads',
            'downloads folder': '~/Downloads',
            'download folder': '~/Downloads',
            'documents': '~/Documents',
            'document': '~/Documents',
            'documents folder': '~/Documents',
            'desktop': '~/Desktop',
            'pictures': '~/Pictures',
            'pics': '~/Pictures',
            'photos': '~/Pictures',
            'music': '~/Music',
            'songs': '~/Music',
            'videos': '~/Videos',
            'movies': '~/Videos',
            'home': '~',
            'home folder': '~',
            'home directory': '~',
            'homepage': '~',
            'recent': 'recent:///',
            'trash': 'trash:///',
            'applications': '/usr/share/applications',
        }
        # Check if target matches a location key or ends with a known location suffix
        if target in location_map:
            return ("open_location", {"path": location_map[target]})
        for key, path in location_map.items():
            if target.endswith(' ' + key) or target == key:
                return ("open_location", {"path": path})

        # Has a file extension -> open as file
        if re.search(r'\.\w{2,5}$', target) and not target.startswith('.'):
            return ("open_file", {"filename": target})

        # Otherwise open as app
        return ("open_app", {"app": target})

    # "go to <location>"
    go_match = re.search(r'go\s+to\s+(.+?)$', text)
    if go_match:
        loc = go_match.group(1).strip().rstrip('.')
        location_map = {
            'downloads': '~/Downloads',
            'download': '~/Downloads',
            'documents': '~/Documents',
            'document': '~/Documents',
            'desktop': '~/Desktop',
            'pictures': '~/Pictures',
            'music': '~/Music',
            'videos': '~/Videos',
            'home': '~',
            'recent': 'recent:///',
            'trash': 'trash:///',
        }
        if loc in location_map:
            return ("open_location", {"path": location_map[loc]})
        return ("open_app", {"app": loc})

    # ====== CLOSE / KILL (check kill_process before generic close) ======
    proc_match = re.search(r'(?:kill|stop|end)\s+process\s+(.+?)$', text)
    if proc_match:
        return ("kill_process", {"name": proc_match.group(1).strip().rstrip('.')})

    close_match = re.search(r'(?:close|kill|quit|exit|terminate)\s+(.+?)$', text)
    if close_match:
        app = close_match.group(1).strip().rstrip('.')
        app = re.sub(r'\s+(?:please|for\s+me|now)$', '', app).strip()
        for art in ['the ', 'my ', 'a ', 'an ']:
            if app.startswith(art):
                app = app[len(art):]
                break
        if app:
            return ("close_app", {"app": app.strip()})

    # ====== WEATHER ======
    if any(k in text for k in ['weather', 'temperature outside', 'how cold', 'how hot',
                                "what's the weather", "what is the weather"]):
        return ("weather", {})

    # ====== TIME / DATE ======
    if any(k in text for k in ['what time', 'time is it', 'current time', 'tell me the time',
                                "what's the time", "what time is it"]):
        return ("time", {})
    if any(k in text for k in ["what's the date", "what date", "what day",
                                "today's date", "date today", "tell me the date"]):
        return ("date", {})

    # ====== SYSTEM INFO ======
    if any(k in text for k in ['system info', 'system information', "what's my system",
                                'my computer', 'computer info', 'computer information',
                                'specs', 'system specs', 'hardware info']):
        return ("system_info", {})

    # ====== SYSTEM STATS ======
    if any(k in text for k in ['cpu usage', 'memory usage', 'ram usage', 'how much',
                                'usage', 'system usage', 'performance', 'system load',
                                'how is my system']):
        return ("system_stats", {})

    # ====== SCREENSHOT ======
    if any(k in text for k in ['screenshot', 'capture screen', 'screen shot',
                                'take picture', 'take screenshot', 'capture the screen']):
        return ("screenshot", {})

    # ====== WEB SEARCH ======
    search_match = re.search(r'(?:search\s+(?:for\s+)?|google\s+|search\s+web\s+for\s+|search\s+the\s+web\s+for\s+)(.+?)$', text)
    if search_match:
        query = search_match.group(1).strip().rstrip('.')
        if query:
            return ("web_search", {"query": query})

    # ====== PLAY MEDIA ======
    play_match = re.search(r'play\s+(.+?)$', text)
    if play_match:
        query = play_match.group(1).strip().rstrip('.')
        query = re.sub(r'\s+(?:please|for\s+me|now|on\s+youtube|in\s+youtube)$', '', query).strip()
        if query and not any(k in query for k in ['a game', 'game']):
            return ("play_media", {"query": query})

    # ====== FILE OPERATIONS ======
    find_match = re.search(r'(?:find|search\s+for|look\s+for|locate|where\s+is)\s+(.+?)$', text)
    if find_match:
        filename = find_match.group(1).strip().rstrip('.')
        if filename:
            return ("find_file", {"filename": filename})

    # create folder
    folder_match = re.search(r'(?:create|make|new)\s+(?:a\s+)?folder\s+(?:called\s+|named\s+)?(.+?)$', text)
    if folder_match:
        name = folder_match.group(1).strip().rstrip('.')
        if name:
            return ("create_item", {"name": name, "type": "folder"})

    # create file
    file_match = re.search(r'(?:create|make|new)\s+(?:a\s+)?file\s+(?:called\s+|named\s+)?(.+?)$', text)
    if file_match:
        name = file_match.group(1).strip().rstrip('.')
        if name:
            return ("create_item", {"name": name, "type": "file"})

    # ====== VOLUME ======
    if any(k in text for k in ['volume up', 'increase volume', 'turn it up',
                                'louder', 'increase sound', 'volume increase']):
        return ("volume", {"action": "up"})
    if any(k in text for k in ['volume down', 'decrease volume', 'turn it down',
                                'quieter', 'lower volume', 'volume decrease']):
        return ("volume", {"action": "down"})
    if any(k in text for k in ['mute', 'mute volume', 'mute sound', 'silent',
                                'turn off sound', 'volume off']):
        return ("volume", {"action": "mute"})

    # ====== CALCULATE ======
    calc_match = re.search(r'(?:calculate|compute|what\s+is|what\'s)\s+(.+?)$', text)
    if calc_match:
        expr = calc_match.group(1).strip().rstrip('.?')
        if re.match(r'^[\d\s\+\-\*\/\(\)\.\,%]+$', expr):
            return ("calculate", {"expression": expr})

    # ====== PROCESS MANAGEMENT ======
    if any(k in text for k in ['top processes', 'list processes', 'running processes',
                                "what's running", 'list running', 'show processes']):
        return ("processes", {})

    # ====== TIMERS / REMINDERS ======
    timer_match = re.search(r'(?:set\\s+(?:a\\s+)?timer|remind\\s+me\\s+in|countdown)\\s+(?:for\\s+)?(.+?)$', text)
    if timer_match:
        raw = timer_match.group(1).strip().rstrip('.')
        m = re.search(r'^(\\d+)\\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\\s+(?:to\\s+|for\\s+)?(.+)?$', raw)
        if m:
            value = int(m.group(1))
            unit = m.group(2)
            note = (m.group(3) or '').strip()
            if not note:
                note = 'timer'
            secs = value
            if unit.startswith('minute') or unit.startswith('min'):
                secs = value * 60
            elif unit.startswith('hour') or unit.startswith('hr'):
                secs = value * 3600
            return ("set_timer", {"text": note, "seconds": str(secs)})
        return ("set_timer", {"text": raw, "seconds": "60"})

    reminder_match = re.search(r'(?:set\\s+(?:a\\s+)?reminder|remind\\s+me)(?:\\s+to\\s+)?(.+)$', text)
    if reminder_match:
        raw = reminder_match.group(1).strip().rstrip('.')
        m = re.search(r'^(?:in\\s+)?(\\d+)\\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\\s+(?:to\\s+|for\\s+)?(.+)?$', raw)
        if m:
            value = int(m.group(1))
            unit = m.group(2)
            note = (m.group(3) or '').strip()
            if not note:
                note = 'reminder'
            secs = value
            if unit.startswith('minute') or unit.startswith('min'):
                secs = value * 60
            elif unit.startswith('hour') or unit.startswith('hr'):
                secs = value * 3600
            return ("set_reminder", {"text": note, "seconds": str(secs)})
        return ("set_reminder", {"text": raw, "seconds": "60"})

    if 'list reminders' in text or 'show reminders' in text or 'my timers' in text or 'list timers' in text:
        return ("list_reminders", {})

    if 'read notifications' in text or 'check notifications' in text or 'any notifications' in text:
        return ("read_notifications", {})

    # ====== UPTIME ======
    if any(k in text for k in ['uptime', 'how long', 'system uptime', 'how long has my computer']):
        return ("uptime", {})

    # ====== DIAGNOSTICS ======
    if any(k in text for k in ['diagnostics', 'system diagnostics', 'run diagnostics', 'full diagnostics']):
        return ("diagnostics", {})

    # Default to chat
    return ("chat", {"text": raw})
