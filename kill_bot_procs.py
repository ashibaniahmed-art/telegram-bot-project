import psutil, os
killed = []
for p in psutil.process_iter(['pid','cmdline']):
    try:
        cmd = ' '.join(p.info['cmdline']) if p.info['cmdline'] else ''
        if 'bot.py' in cmd and p.pid != os.getpid():
            try:
                p.kill()
                killed.append(p.pid)
            except Exception:
                pass
    except Exception:
        pass
print('killed_pids:', killed)
