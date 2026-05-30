#!/usr/bin/env python3
"""
Conversion Dashboard Generator
================================
Measures CONVERSION, not activity. Counts only outcomes that required Dave to hit
"send": sent outreach, replies/calls, applications submitted, posts published, demos
shipped. Aware/Quant is reported as *shipped / in TestFlight*, never as idle-guilt.

Auto-pulls straight from the filesystem — zero daily manual entry. See
~/Documents/Claude/Career/HOW-TO-LOG.md for the (optional, seconds-long) send signals.

Canonical repo: ~/Developer/dashboard  (the copies in ~/Documents/Claude/Dashboard and
~/Documents/Claude/dashboard-app are deprecated — do not generate into them).
"""

import json
import re
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

# ── Paths ───────────────────────────────────────────────────────────
HOME     = Path.home()
CLAUDE   = HOME / "Documents" / "Claude"
CAREER   = CLAUDE / "Career"
OUTREACH = CAREER / "Outreach"
LINKEDIN = CAREER / "LinkedIn"
REPO     = HOME / "Developer" / "dashboard"
QUANT    = HOME / "Developer" / "Quant"
OUTPUT   = REPO / "index.html"

NOW       = datetime.now()
TODAY     = NOW.date()
WEEK_START = TODAY - timedelta(days=6)          # 7-day rolling window, incl. today


def week_windows(n=8):
    """n consecutive 7-day windows, oldest→newest, the last ending today."""
    return [(TODAY - timedelta(days=7 * k + 6), TODAY - timedelta(days=7 * k))
            for k in range(n - 1, -1, -1)]


def cells_for(dates, windows):
    """1 if at least one date falls in the window, else 0 (controllable inputs)."""
    return [1 if any(d and s <= d <= e for d in dates) else 0 for (s, e) in windows]


# ── Small parsers ───────────────────────────────────────────────────
def in_week(d):
    return d is not None and WEEK_START <= d <= TODAY


def parse_iso(s):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def date_from_name(p):
    m = re.match(r"(\d{8})", p.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except Exception:
        return None


def read_log(path):
    """Parse a ` date | a | b ` pipe log, skipping #comments / blanks."""
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        d = parse_iso(parts[0]) if parts else None
        if d:
            rows.append({"date": d, "a": parts[1] if len(parts) > 1 else "",
                         "b": parts[2] if len(parts) > 2 else ""})
    return rows


def read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def first_match(text, pattern, group=1, default=""):
    m = re.search(pattern, text)
    return m.group(group).strip() if m else default


# ── Outreach: drafted → sent → replied ──────────────────────────────
def load_outreach():
    drafts = []
    for p in sorted(OUTREACH.glob("*Connection Draft*.md")):
        txt = p.read_text(errors="ignore")
        name = first_match(txt, r"\*\*(.+?)\*\*", default="(unnamed)")
        name = re.sub(r'["“”]', "", name).strip()
        d = date_from_name(p) or parse_iso(first_match(txt, r"#.*?(\d{4}-\d{2}-\d{2})"))
        sent_inline = parse_iso(first_match(txt, r"Sent:\s*(\d{4}-\d{2}-\d{2})"))
        reply_inline = parse_iso(first_match(txt, r"Replied:\s*(\d{4}-\d{2}-\d{2})"))
        drafts.append({"name": name, "date": d,
                       "sent": sent_inline, "replied": reply_inline})

    sent_log = read_log(OUTREACH / "sent.log")
    reply_log = read_log(OUTREACH / "replies.log")

    def name_key(n):
        return re.sub(r"[^a-z]", "", (n or "").lower())

    # Fold logs onto drafts by fuzzy name match; keep unmatched log rows too.
    sent_events = [{"name": r["a"], "date": r["date"]} for r in sent_log]
    reply_events = [{"name": r["a"], "date": r["date"], "kind": r["b"] or "reply"}
                    for r in reply_log]

    # Auto-detected replies from Gmail (LinkedIn acceptances/messages + email
    # replies), written by the scheduled task. Already name-matched to targets at
    # write-time, so only genuine responses to Dave's outreach land here.
    for r in read_jsonl(OUTREACH / "replies-gmail.jsonl"):
        d = parse_iso(str(r.get("date", "")))
        if d and r.get("name"):
            reply_events.append({"name": r["name"], "date": d,
                                 "kind": r.get("kind", "reply")})

    # Fold inline draft signals (Sent:/Replied: lines) into the event sets, so
    # every send/reply is counted from ONE place regardless of where it was logged.
    for d in drafts:
        if d["sent"]:
            sent_events.append({"name": d["name"], "date": d["sent"]})
        if d["replied"]:
            reply_events.append({"name": d["name"], "date": d["replied"],
                                 "kind": "reply"})

    def dedupe(events):
        seen, out = set(), []
        for ev in sorted(events, key=lambda e: e["date"]):
            k = (name_key(ev["name"]), ev["date"])
            if k not in seen:
                seen.add(k)
                out.append(ev)
        return out

    sent_events = dedupe(sent_events)
    reply_events = dedupe(reply_events)

    def fuzzy(a, b):
        a, b = name_key(a), name_key(b)
        return bool(a and b and (a in b or b in a))

    # Counts come straight from the deduped event sets — never double-counted.
    sent_dates = [e["date"] for e in sent_events]
    reply_dates = [e["date"] for e in reply_events]

    # Per-person funnel status (display only) via fuzzy name match.
    for d in drafts:
        d["sent"] = d["sent"] or next((e["date"] for e in sent_events
                                       if fuzzy(d["name"], e["name"])), None)
        d["replied"] = d["replied"] or next((e["date"] for e in reply_events
                                             if fuzzy(d["name"], e["name"])), None)

    people = []
    for d in sorted(drafts, key=lambda x: x["date"] or date.min, reverse=True):
        status = "replied" if d["replied"] else ("sent" if d["sent"] else "drafted")
        people.append({"name": d["name"],
                       "date": d["date"].isoformat() if d["date"] else "—",
                       "status": status})

    # Oldest still-unsent draft = the thing to send next.
    unsent = sorted([d for d in drafts if not d["sent"] and d["date"]],
                    key=lambda x: x["date"])
    next_to_send = unsent[0] if unsent else None

    return {
        "drafted_total": len(drafts),
        "sent_total": len(sent_dates),
        "replied_total": len(reply_dates),
        "sent_week": sum(1 for x in sent_dates if in_week(x)),
        "replied_week": sum(1 for x in reply_dates if in_week(x)),
        "sent_dates": sent_dates,
        "people": people[:6],
        "next_to_send": next_to_send,
    }


# ── Published posts (drafts are NOT posts — published = you hit publish) ─
def load_published():
    draft_files = sorted(LINKEDIN.glob("archive/*.md"))
    cur = LINKEDIN / "current-draft.md"
    if cur.exists():
        draft_files.append(cur)
    drafted_total = len(draft_files)

    # Published counts ONLY an explicit "I hit publish" signal: a line in
    # published.log, or a `Published: YYYY-MM-DD` marker inside the draft.
    items = []
    for r in read_log(LINKEDIN / "published.log"):
        items.append({"title": r["a"] or "Untitled", "date": r["date"]})
    for p in draft_files:
        txt = p.read_text(errors="ignore")
        pub = parse_iso(first_match(txt, r"Published:\s*(\d{4}-\d{2}-\d{2})"))
        if pub:
            items.append({"title": first_match(txt, r"#\s*(.+)", default=p.stem),
                          "date": pub})

    seen, dedup = set(), []
    for it in sorted([i for i in items if i["date"]],
                     key=lambda x: x["date"], reverse=True):
        k = (it["title"][:40].lower(), it["date"])
        if k not in seen:
            seen.add(k)
            dedup.append(it)
    items = dedup

    return {
        "drafted": drafted_total,
        "total": len(items),
        "week": sum(1 for i in items if in_week(i["date"])),
        "latest": items[0] if items else None,
        "recent": [{"title": i["title"][:90],
                    "date": i["date"].isoformat()} for i in items[:4]],
        "draft_waiting": drafted_total > len(items),
        "dates": [i["date"] for i in items],
        "note": "Drafts aren't posts — published counts only what you actually "
                "published (published.log or a Published: line).",
    }


# ── Applications pipeline ───────────────────────────────────────────
def load_applications():
    rows = read_jsonl(CAREER / "applications.jsonl")
    order = ["submitted", "screen", "interview", "offer", "rejected"]
    by_status = {s: 0 for s in order}
    recent, dates = [], []
    week = 0
    for r in rows:
        st = (r.get("status") or "submitted").lower()
        by_status[st] = by_status.get(st, 0) + 1
        d = parse_iso(str(r.get("date", "")))
        if d:
            dates.append(d)
        if in_week(d):
            week += 1
        recent.append({"company": r.get("company", "—"),
                       "role": r.get("role", ""),
                       "status": st,
                       "date": d.isoformat() if d else "—",
                       "link": r.get("link", "")})
    recent.sort(key=lambda x: x["date"], reverse=True)
    active = sum(by_status.get(s, 0) for s in ("submitted", "screen", "interview", "offer"))
    return {"total": len(rows), "week": week, "active": active,
            "by_status": by_status, "recent": recent[:5], "dates": dates}


# ── Demos shipped ───────────────────────────────────────────────────
def load_demos():
    rows = read_jsonl(CAREER / "demos.jsonl")
    items = []
    for r in rows:
        d = parse_iso(str(r.get("date", "")))
        items.append({"title": r.get("title", "Demo"),
                      "url": r.get("url", ""),
                      "date": d.isoformat() if d else "—",
                      "_d": d})
    items.sort(key=lambda x: x["_d"] or date.min, reverse=True)
    return {"total": len(items),
            "week": sum(1 for i in items if in_week(i["_d"])),
            "dates": [i["_d"] for i in items if i["_d"]],
            "rows": [{k: v for k, v in i.items() if k != "_d"} for i in items[:4]]}


# ── Aware / Quant: shipping signal (never idle-guilt) ───────────────
def load_aware():
    info = {"in_testflight": True, "tests": None, "loc": None, "commits": None,
            "last_shipped": "—", "days_since": None, "last_msg": ""}
    # Real shipping signal from git.
    try:
        last = subprocess.run(
            ["git", "-C", str(QUANT), "log", "-1", "--format=%ad|%s", "--date=short"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        if "|" in last:
            ds, msg = last.split("|", 1)
            d = parse_iso(ds)
            if d:
                info["last_shipped"] = d.strftime("%b %d")
                info["days_since"] = (TODAY - d).days
            info["last_msg"] = msg.strip()
        count = subprocess.run(
            ["git", "-C", str(QUANT), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        info["commits"] = int(count) if count.isdigit() else None
    except Exception:
        pass
    # Test count + LOC from the latest Project Movement report (richer than git).
    movements = sorted(CAREER.glob("*Project Movement.md"))
    if movements:
        txt = movements[-1].read_text(errors="ignore")
        t = first_match(txt, r"(\d+)\s+tests")
        loc = first_match(txt, r"~?\s*(\d+K)\s+lines")
        info["tests"] = int(t) if t.isdigit() else info["tests"]
        info["loc"] = loc or info["loc"]
    return info


# ── Target roles (read-only, from latest job scan) ──────────────────
def load_targets():
    scans = sorted(CAREER.glob("*Job Market Scan.md"))
    if not scans:
        return []
    txt = scans[-1].read_text(errors="ignore")
    targets = []
    for block in re.split(r"\n###\s+\d+\.\s+", txt)[1:]:
        head = block.splitlines()[0].strip()
        company = head.split("—")[0].strip() if "—" in head else head
        role = first_match(block, r"\*\*Title\*\*\s*\|\s*(.+)")
        salary = first_match(block, r"\*\*Salary\*\*\s*\|\s*(.+)")
        link = first_match(block, r"\*\*Link\*\*\s*\|\s*(\S+)")
        targets.append({"company": company, "role": role or head,
                        "salary": salary, "link": link})
    return targets[:4]


# ── Family (presence over occurrence — a mirror, not a judge) ───────
def _friendly_day(d):
    if d == TODAY:
        return "Today"
    if d == TODAY + timedelta(days=1):
        return "Tomorrow"
    if 0 < (d - TODAY).days < 7:
        return d.strftime("%a")
    return d.strftime("%b %d")


def _load_json(name):
    p = CLAUDE / name
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def load_presence():
    """Presence during family blocks — a mirror, not a judge. Three honest
    signals: phone-down (objective, the in-moment lever), your own rating, and
    Jena's read on how present you actually were. Empty until captured — shown
    as a setup prompt, never as a 0/guilt score."""
    rows = read_jsonl(CLAUDE / "family-presence.jsonl")
    if not rows:
        return {"has_data": False}
    recent = rows[-28:]

    def avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    self_r = [r["present_rating"] for r in recent if r.get("present_rating")]
    jena_r = [r["jena_rating"] for r in recent if r.get("jena_rating")]
    phone = [r["phone_minutes"] for r in recent if r.get("phone_minutes") is not None]
    last = rows[-1]
    return {
        "has_data": True,
        "avg_rating": avg(self_r), "n_ratings": len(self_r),
        "avg_jena": avg(jena_r), "n_jena": len(jena_r),
        "avg_phone": int(sum(phone) / len(phone)) if phone else None,
        "last": {"date": last.get("date", "—"),
                 "block": last.get("block", "family"),
                 "rating": last.get("present_rating"),
                 "jena_rating": last.get("jena_rating"),
                 "phone_minutes": last.get("phone_minutes")},
    }


def load_friends():
    """Keeping up with friends — surface who's overdue vs the cadence you set,
    plus upcoming birthdays as natural reach-out moments."""
    data = _load_json("friendships.json")
    roster = data.get("friends", [])
    tracked = []
    for fr in roster:
        d = parse_iso(str(fr.get("last_contact") or ""))
        cad = fr.get("cadence_weeks", 12)
        wk = (TODAY - d).days // 7 if d else None
        tracked.append({"name": fr.get("name", "—"), "weeks_since": wk,
                        "cadence": cad, "last": d.strftime("%b %d") if d else None,
                        "overdue": wk is not None and wk >= cad})
    overdue = sorted([t for t in tracked if t["overdue"]],
                     key=lambda x: x["weeks_since"], reverse=True)
    cal = _load_json("family-calendar.json")
    birthdays = [u for u in cal.get("upcoming", []) if u.get("observance")]
    return {
        "count": len(roster),
        "in_touch": sum(1 for t in tracked if t["weeks_since"] is not None
                        and not t["overdue"]),
        "untracked": sum(1 for t in tracked if t["weeks_since"] is None),
        "overdue": overdue[:4],
        "birthdays": birthdays[:4],
    }


def load_family():
    f = _load_json("family-activity.json")
    out = {
        "suggestion": f.get("suggestion"),
        "category": (f.get("category") or "").title(),
        "weather": f.get("weather"),
        "has_calendar": False,
        "date_night": None, "adele": None, "tonight": None, "upcoming": [],
        "presence": load_presence(),
        "action": None,
    }

    cal = _load_json("family-calendar.json")
    if cal:
        out["has_calendar"] = True
        dn = cal.get("last_date_night") or {}
        if dn.get("date") and parse_iso(dn["date"]):
            d = parse_iso(dn["date"])
            out["date_night"] = {"weeks_since": (TODAY - d).days // 7,
                                 "title": dn.get("title", ""),
                                 "date": d.strftime("%b %d")}
        ad = cal.get("last_adele_1on1") or {}
        if ad.get("date") and parse_iso(ad["date"]):
            d = parse_iso(ad["date"])
            out["adele"] = {"weeks_since": (TODAY - d).days // 7,
                            "title": ad.get("title", ""),
                            "date": d.strftime("%b %d")}
        tn = cal.get("tonight_childcare") or {}
        if tn.get("date") and parse_iso(tn["date"]) == TODAY:
            out["tonight"] = {"sitter": tn.get("sitter", "a sitter"),
                              "window": tn.get("window", "")}
        for u in cal.get("upcoming", []):
            d = parse_iso(str(u.get("date", "")))
            if d:
                out["upcoming"].append({"label": _friendly_day(d),
                                        "title": u.get("title", ""),
                                        "observance": bool(u.get("observance"))})

    out["action"] = family_action(out)
    return out


def family_action(fam):
    """ONE family action. Presence-first: when a block is happening, the lever
    isn't 'show up', it's 'be there for it' — phone down."""
    dn = fam.get("date_night")
    wk = dn["weeks_since"] if dn else None
    if fam.get("tonight"):
        t = fam["tonight"]
        why = (f"{wk} weeks since your last ({dn['title']}, {dn['date']}). "
               "Phone in the drawer — be there for it.") if wk is not None \
              else "Childcare's covered. Phone in the drawer — be there for it."
        return {"tag": "Tonight",
                "text": f"{t['sitter']} has Adele {t['window']} — take Jena out.",
                "why": why}
    if wk is not None and wk >= 2:
        return {"tag": "Date night",
                "text": "Plan a date night this week.",
                "why": f"{wk} weeks since the last ({dn['title']}, {dn['date']})."}
    adele = fam.get("adele")
    if (adele is None or adele.get("weeks_since", 99) >= 2) and fam.get("suggestion"):
        short = fam["suggestion"].split(".")[0][:90]
        return {"tag": "Adele",
                "text": "Carve out 1:1 time with Adele — and be all there.",
                "why": f"Today's idea: {short}."}
    tomorrow = next((u for u in fam.get("upcoming", [])
                     if u["label"] == "Tomorrow"), None)
    if tomorrow:
        return {"tag": "Heads up", "text": f"Tomorrow: {tomorrow['title']}",
                "why": "On the family calendar."}
    return {"tag": "On track",
            "text": "Family time looks balanced this week.",
            "why": "Now protect the attention, not just the time."}


def load_health():
    # Workouts come from the Body & Mind calendar (goal: 3x/week); steps/sleep/HR
    # come from the Apple Watch iCloud Shortcut into health-history.jsonl.
    cal = _load_json("health-calendar.json")
    out = {
        "has_data": False,
        "workouts": cal.get("workouts_this_week"),   # None if calendar not synced
        "goal": cal.get("weekly_goal", 3),
        "steps": "—", "sleep_hours": "—", "resting_hr": "—",
        "avg_steps": "—", "avg_sleep": "—",
    }
    rows = read_jsonl(CLAUDE / "health-history.jsonl")
    if rows:
        last, last7 = rows[-1], rows[-7:]
        out.update({
            "has_data": True,
            "steps": last.get("steps", "—"),
            "sleep_hours": last.get("sleep_hours", "—"),
            "resting_hr": last.get("resting_hr", "—"),
            "avg_steps": int(sum(d.get("steps", 0) for d in last7) / len(last7)),
            "avg_sleep": round(sum(d.get("sleep_hours", 0) for d in last7) / len(last7), 1),
        })

    # 8-week workout cadence strip, aligned to the same windows as the career strips.
    by_end = {w.get("end"): w.get("count", 0) for w in cal.get("weeks", [])}
    goal = out["goal"]
    weeks = []
    for (s, e) in week_windows(8):
        cnt = by_end.get(e.isoformat(), 0)
        level = "full" if cnt >= goal else ("part" if cnt > 0 else "")
        weeks.append({"count": cnt, "level": level})
    out["workout_weeks"] = weeks
    return out


# ── Next action: ONE thing, conversion-first ────────────────────────
def next_action(outreach, apps, published, demos, targets):
    nts = outreach["next_to_send"]
    if nts:
        age = (TODAY - nts["date"]).days if nts["date"] else 0
        return {"text": f"Send your connection to {nts['name']}",
                "why": f"Drafted {age}d ago — still unsent. Hit send today.",
                "tag": "Outreach"}
    if published["draft_waiting"] and published["week"] == 0:
        return {"text": "Publish your LinkedIn draft",
                "why": "It's written and sitting in current-draft.md.",
                "tag": "Publish"}
    if apps["week"] == 0 and targets:
        t = targets[0]
        return {"text": f"Apply: {t['company']} — {t['role']}",
                "why": f"Live target{(' · ' + t['salary']) if t['salary'] else ''}.",
                "tag": "Apply"}
    if demos["week"] == 0:
        return {"text": "Record a 60-sec demo of the posture visualization",
                "why": "A shipped video is worth more than 10 commits.",
                "tag": "Demo"}
    return {"text": "You're converting — keep the cadence.",
            "why": "Sent, applied, published this week. Stay on it.",
            "tag": "On track"}


def main():
    outreach  = load_outreach()
    published = load_published()
    apps      = load_applications()
    demos     = load_demos()
    aware     = load_aware()
    targets   = load_targets()
    family    = load_family()
    friends   = load_friends()
    health    = load_health()

    hero = {
        "sent": outreach["sent_week"],
        "applied": apps["week"],
        "replies": outreach["replied_week"],
        "published": published["week"],
        "demos": demos["week"],
    }
    action = next_action(outreach, apps, published, demos, targets)
    week_label = f"{WEEK_START.strftime('%b %d')} – {TODAY.strftime('%b %d')}"

    # 8-week cadence strips — controllable INPUTS only (never replies/offers).
    wins = week_windows(8)
    trends = {
        "career": [
            {"name": "Sent", "cells": cells_for(outreach["sent_dates"], wins)},
            {"name": "Applied", "cells": cells_for(apps["dates"], wins)},
            {"name": "Published", "cells": cells_for(published["dates"], wins)},
            {"name": "Demos", "cells": cells_for(demos["dates"], wins)},
        ],
        "workouts": health["workout_weeks"],
    }

    env = Environment(loader=FileSystemLoader(str(REPO)), autoescape=True)
    html = env.get_template("template.html").render(
        generated=NOW.strftime("%B %d, %Y · %I:%M %p"),
        week_label=week_label,
        hero=hero, action=action,
        outreach=outreach, published=published, apps=apps, demos=demos,
        aware=aware, targets=targets, family=family, friends=friends, health=health,
        trends=trends,
    )
    OUTPUT.write_text(html)

    line = f"This week → {hero['sent']} sent · {hero['applied']} applied · " \
           f"{hero['replies']} replies · {hero['published']} published · {hero['demos']} demos"
    print(f"✅ Dashboard generated: {OUTPUT}")
    print(f"   {line}")
    print(f"   Next: {action['text']}")


if __name__ == "__main__":
    main()
