# Running the Telegram bot 24/7 (Windows)

This file explains safe ways to run the bot continuously on Windows. Pick one method and follow the steps.

Important notes before you begin
- Ensure you run the bot under your project virtualenv (.venv) so dependencies like `python-telegram-bot` and `python-dotenv` are available.
- Avoid running multiple bot instances at once (getUpdates conflict). If you use webhook vs polling, pick one.
- You may need admin rights for some steps (service creation or scheduled tasks for all users).

Method A — Quick: wrapper loop (restart on crash)
- Purpose: a simple script that restarts the bot if it exits. Easy to start and test.
- Files added: `scripts/run_bot_forever.bat` (already included in the repo).
- How to run now (interactive):

  1. Open cmd.exe in the project folder: `cd "C:\Users\OFOQ\Desktop\مجلد جديد\telegram-bot-project"`
  2. Start the script: `scripts\run_bot_forever.bat`
  3. Logs are appended to `bot.log` in the project folder.

- Pros: simple, restarts automatically. No admin needed.
- Cons: not a true Windows service; process stops when the user logs out (unless you run it in a session that remains active or a background user session).

Method B — Recommended: NSSM (Non-Sucking Service Manager)
- Purpose: run the Python script as a Windows Service that starts at boot and restarts on failure.
- Steps (summary):
  1. Download NSSM from https://nssm.cc/ and extract it (pick the correct architecture).
  2. Install a service via admin command prompt:

     nssm install TelegramBot
     (A GUI will open)
     - Path: C:\Path\to\your\project\.venv\Scripts\python.exe
     - Arguments: C:\Path\to\your\project\bot.py
     - Start directory: C:\Path\to\your\project
     - I/O: set output to C:\Path\to\your\project\bot.log

  3. Configure restart options (under the 'Exit actions' tab: restart on non-zero exit).
  4. Start service: `nssm start TelegramBot` (or Services.msc)

- Pros: behaves like a service, starts at boot, automatic restarts, manageable in Services.msc.
- Cons: extra tool (NSSM) to download; needs admin to install.

Method C — Scheduled Task
- Purpose: schedule the script to run at logon or on system startup and restart on failure.
- Use `schtasks` to create a task that runs at startup with highest privileges.
- Example command (run in elevated cmd):

  schtasks /Create /SC ONSTART /TN "TelegramBot" /TR "cmd /c \"cd /d C:\Path\to\project && .venv\\Scripts\\activate && .venv\\Scripts\\python.exe bot.py\"" /RL HIGHEST /F

- Also consider setting the task to 'Run whether user is logged on or not' and allow it to run with highest privileges.
- Pros: built-in Windows tool, no third-party download.
- Cons: configuration is a bit more brittle (quoting, user context), and task will run under a specific user account.

Method D — Container (Docker)
- Purpose: run the bot inside a Docker container and use any host system orchestration (Docker restart policy, systemd, or a cloud provider).
- Not covered here in detail. Good for production deployments on servers.

Which to pick?
- For personal Windows machines: NSSM or Scheduled Task is best for reliable 24/7 operation.
- For a quick solution during development or for testing: `scripts/run_bot_forever.bat` is easiest.

If you want, I can:
- (A) Start the `scripts/run_bot_forever.bat` now in a background terminal (simple; won't survive reboot), or
- (B) Help you install NSSM and configure a Windows Service (needs your confirmation and admin rights), or
- (C) Create the Task Scheduler entry for you (I will run the `schtasks` command — requires admin and correct quoting). 

Tell me which option you want and I will implement the steps.
