#!/usr/bin/env python3
"""
run.py – Start BOTH the Discord bot and the Flask dashboard in parallel.
Auto-restarts the bot with exponential backoff if it crashes.
"""
import subprocess, sys, os, signal, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))

def stream(proc, prefix):
    for line in iter(proc.stdout.readline, b''):
        print(f"[{prefix}] {line.decode().rstrip()}", flush=True)

running = True

def shutdown(sig, frame):
    global running
    running = False
    print("\nShutting down…", flush=True)
    sys.exit(0)

signal.signal(signal.SIGINT,  shutdown)
signal.signal(signal.SIGTERM, shutdown)

bot_env = {**os.environ, "PYTHONUNBUFFERED": "1"}

# ── Dashboard ─────────────────────────────────────────────────────────────────
dash_proc = subprocess.Popen(
    [sys.executable, os.path.join(ROOT, "dashboard", "app.py")],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=bot_env,
)
threading.Thread(target=stream, args=(dash_proc, "DASH"), daemon=True).start()

# ── Bot (auto-restart with exponential backoff) ───────────────────────────────
def run_bot():
    delay    = 5
    max_delay = 300
    attempts = 0
    while running:
        attempts += 1
        print(f"[BOT ] Starting bot (attempt {attempts})…", flush=True)
        proc = subprocess.Popen(
            [sys.executable, "-m", "bot.bot"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=bot_env, cwd=ROOT,
        )
        threading.Thread(target=stream, args=(proc, "BOT "), daemon=True).start()
        proc.wait()
        if not running:
            break
        code = proc.returncode
        print(f"[BOT ] Exited (code {code}). Restarting in {delay}s…", flush=True)
        time.sleep(delay)
        delay = min(delay * 2, max_delay)

threading.Thread(target=run_bot, daemon=True).start()

dash_proc.wait()
