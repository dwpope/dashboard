#!/usr/bin/env python3
"""
Three-Pillar Life Dashboard Generator
Reads JSON data files from ~/Documents/Claude/ and renders an HTML dashboard.

Pillars:
  1. BUILD  — Quant/Aware project status, code-tutor progress
  2. MOVE   — Career transition, outreach, intel
  3. THRIVE — Health metrics, nutrition, family check-ins
"""

import json
import os
from datetime import datetime, date
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

# ── Paths ──────────────────────────────────────────────────────────
DATA_DIR = Path.home() / "Documents" / "Claude"
REPO_DIR = Path.home() / "Developer" / "dashboard"
OUTPUT   = REPO_DIR / "index.html"

def load_json(name, default=None):
    """Load a JSON file from DATA_DIR, returning default on any error."""
    p = DATA_DIR / name
    if not p.exists():
        return default if default is not None else {}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}

def load_jsonl(name, max_lines=90):
    """Load last N lines from a JSONL file."""
    p = DATA_DIR / name
    if not p.exists():
        return []
    lines = []
    try:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return lines[-max_lines:]
    except Exception:
        return []

def compute_streaks(health_data):
    """Compute current streaks from health data."""
    if not health_data:
        return {"steps_7k": 0, "sleep_7h": 0, "workout": 0}

    streaks = {"steps_7k": 0, "sleep_7h": 0, "workout": 0}
    for entry in reversed(health_data):
        if entry.get("steps", 0) >= 7000:
            streaks["steps_7k"] += 1
        else:
            break
    for entry in reversed(health_data):
        if entry.get("sleep_hours", 0) >= 7.0:
            streaks["sleep_7h"] += 1
        else:
            break
    for entry in reversed(health_data):
        if entry.get("workouts"):
            streaks["workout"] += 1
        else:
            break
    return streaks

def latest_health(health_data):
    """Get the most recent health entry."""
    if not health_data:
        return {
            "steps": "—", "sleep_hours": "—", "resting_hr": "—",
            "hrv": "—", "vo2max": "—", "workouts": []
        }
    return health_data[-1]

def protein_streak(nutrition_data):
    """Count consecutive days with protein_all_meals=true."""
    streak = 0
    for entry in reversed(nutrition_data):
        if entry.get("protein_all_meals"):
            streak += 1
        else:
            break
    return streak

def status_color(days):
    """Return green/amber/red based on days of inactivity."""
    if days <= 3:
        return "green"
    elif days <= 7:
        return "amber"
    return "red"

def main():
    now = datetime.now()
    today = date.today()

    # ── Load all data sources ──
    quant       = load_json("quant-status.json", {"video_shipped": False, "next_milestone": "—", "days_since_progress": 0})
    outreach    = load_json("outreach.json", {"target": 10, "people": []})
    career      = load_json("career-intel.json", {"act_on": []})
    tutor       = load_json("code-tutor-profile.json", {"days_since_session": 0, "weakest_area": "—"})
    health_data = load_jsonl("health-history.jsonl")
    nutrition   = load_jsonl("nutrition.jsonl")
    family_raw  = load_json("family-checkin.json", {"last_checkin": None, "next_due": None})
    family_act  = load_json("family-activity.json", {"recent": None})

    # ── Compute derived values ──
    health      = latest_health(health_data)
    streaks     = compute_streaks(health_data)
    p_streak    = protein_streak(nutrition)
    outreach_count = len(outreach.get("people", []))
    outreach_target = outreach.get("target", 10)

    quant_color = status_color(quant.get("days_since_progress", 0))
    tutor_color = status_color(tutor.get("days_since_session", 0))

    # Health week averages
    last_7 = health_data[-7:] if len(health_data) >= 7 else health_data
    avg_steps = int(sum(d.get("steps", 0) for d in last_7) / max(len(last_7), 1)) if last_7 else "—"
    avg_sleep = round(sum(d.get("sleep_hours", 0) for d in last_7) / max(len(last_7), 1), 1) if last_7 else "—"

    # Steps history for sparkline (last 14 days)
    steps_history = [d.get("steps", 0) for d in health_data[-14:]]
    sleep_history = [d.get("sleep_hours", 0) for d in health_data[-14:]]

    # ── Render template ──
    env = Environment(
        loader=FileSystemLoader(str(REPO_DIR)),
        autoescape=True
    )
    template = env.get_template("template.html")

    html = template.render(
        generated=now.strftime("%B %d, %Y · %I:%M %p"),
        today=today.isoformat(),
        # BUILD pillar
        quant=quant,
        quant_color=quant_color,
        tutor=tutor,
        tutor_color=tutor_color,
        # MOVE pillar
        outreach=outreach,
        outreach_count=outreach_count,
        outreach_target=outreach_target,
        career_actions=career.get("act_on", []),
        # THRIVE pillar
        health=health,
        streaks=streaks,
        avg_steps=avg_steps,
        avg_sleep=avg_sleep,
        p_streak=p_streak,
        steps_history=json.dumps(steps_history),
        sleep_history=json.dumps(sleep_history),
        nutrition_data=nutrition,
        family=family_raw,
        family_activity=family_act,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        f.write(html)

    print(f"✅ Dashboard generated: {OUTPUT}")
    print(f"   Pillars: BUILD({quant_color}) · MOVE({outreach_count}/{outreach_target}) · THRIVE({len(health_data)} days tracked)")

if __name__ == "__main__":
    main()
