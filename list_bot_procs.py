import psutil
for p in psutil.process_iter(['pid','cmdline']):
    try:
        cmd = ' '.join(p.info['cmdline']) if p.info['cmdline'] else ''
        if 'bot.py' in cmd:
            print('PID:', p.info['pid'])
            print('CMD:', repr(cmd))
            print('-' * 60)
    except Exception:
        pass
