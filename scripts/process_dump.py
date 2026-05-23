#!/usr/bin/env python3
"""
Process Telegram brain-dump messages into a structured daily plan.

Flow per run:
1. Read last-processed Telegram update_id from state/last_processed.json
2. Call Telegram getUpdates with offset = last_id + 1
3. Filter for text messages from Abilash's chat
4. If no new messages, exit quietly (state still advances if Telegram had non-text updates we should skip in future)
5. Read context.md (his ADHD context — daily anchors, recurring projects, voice)
6. Call Gemini API with system context + new messages -> structured plan JSON
7. Validate JSON, PATCH the plan.json file in his GitHub Gist
8. Update state file (workflow commits it back)
9. Send Telegram message confirming the plan is ready
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests

# ============ Config ============
REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / 'state' / 'last_processed.json'
CONTEXT_FILE = REPO_ROOT / 'context.md'

GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
GIST_ID = os.environ['GIST_ID']
GIST_TOKEN = os.environ['GIST_TOKEN']

GEMINI_MODEL = 'gemini-2.5-flash'
IST = timezone(timedelta(hours=5, minutes=30))


# ============ State helpers ============
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {'last_update_id': 0}


def save_state(state):
    STATE_FILE.parent.mkdir(exist_ok=True, parents=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + '\n')


# ============ Telegram ============
def get_telegram_updates(offset=None):
    """Fetch new updates. offset=N tells Telegram to forget updates < N (acks)."""
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates'
    params = {'timeout': 0}
    if offset is not None:
        params['offset'] = offset
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get('ok'):
        raise RuntimeError(f"Telegram getUpdates error: {data}")
    return data.get('result', [])


def send_telegram_message(text):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    r = requests.post(url, data={
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'disable_web_page_preview': 'true',
    }, timeout=30)
    r.raise_for_status()


# ============ Gemini ============
def call_gemini(system_prompt, user_content):
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/'
        f'{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}'
    )
    payload = {
        'system_instruction': {'parts': [{'text': system_prompt}]},
        'contents': [{
            'role': 'user',
            'parts': [{'text': user_content}],
        }],
        'generationConfig': {
            'temperature': 0.4,
            'response_mime_type': 'application/json',
        },
    }
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    try:
        return data['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response shape: {json.dumps(data)[:500]}") from e


# ============ Gist ============
def update_gist(plan_json_str):
    url = f'https://api.github.com/gists/{GIST_ID}'
    payload = {'files': {'plan.json': {'content': plan_json_str}}}
    r = requests.patch(url, headers={
        'Authorization': f'token {GIST_TOKEN}',
        'Accept': 'application/vnd.github+json',
    }, json=payload, timeout=30)
    r.raise_for_status()


# ============ Prompt assembly ============
def build_system_prompt(context_md):
    today_ist = datetime.now(IST).strftime('%Y-%m-%d')
    return f"""You are Abilash's external executive-function assistant for his ADHD. \
Your job here is to take his messy morning brain dump (a series of text messages \
sent to his Telegram bot) and produce a structured daily plan as JSON.

## Today's date (Asia/Kolkata)
{today_ist}

## Everything you need to know about Abilash, in his own context
{context_md}

## What you output
ONLY a single JSON object — no preamble, no markdown code fences, no explanation. \
Schema (strict):

{{
  "date": "YYYY-MM-DD (today, in IST)",
  "focus": [
    {{ "text": "short imperative task", "meta": "one short line — why/when/encouragement" }}
  ],
  "wins": ["short 5-min quick win", "another"],
  "park": ["thing to defer or come back to later", "another"],
  "version": "ISO timestamp with +05:30 offset, current moment"
}}

## Rules
- focus: 3-5 items, ordered most important first (item 0 becomes NEXT in the app). \
ALWAYS surface his non-negotiable daily anchors (post-brush push-ups, food-then-meds, \
office by 10am, protect 10:00-11:30 window if VSTS Directive is in the dump).
- wins: optional 5-minute tasks. Empty list is fine.
- park: things he mentioned that shouldn't crowd today (aspirational, blocked, low-energy). \
Always populate if he mentioned things you didn't lift into focus — don't drop silently.
- Voice: dry, slightly sardonic, like a friend who knows him. NEVER use guilt language \
("you missed/forgot/should/need to"). NEVER use corporate productivity cliches \
("crush your day", "level up", "seize the morning"). No emoji in plan content.
- "meta" on each focus item: one short sentence, max ~12 words. Concrete (why, when, \
or a tiny encouragement). Match his voice.
- Watch his patterns: don't let push-ups habit drop off. Park things that compete with \
the VSTS Directive window. If he mentioned ADHD Assistant project work, only put it in \
focus for weekends/evenings — never in the protected office window.
- If the dump is sparse or unclear: still produce a valid plan, falling back to his daily \
anchors only. Output valid JSON no matter what.
"""


def build_user_content(text_msgs):
    joined = '\n---\n'.join(text_msgs)
    return f"Brain-dump messages from Abilash (in arrival order, oldest first):\n\n{joined}"


# ============ Main ============
def main():
    state = load_state()
    last_id = int(state.get('last_update_id', 0) or 0)

    # Tell Telegram to ack older updates by passing offset = last_id + 1
    offset = last_id + 1 if last_id else None
    updates = get_telegram_updates(offset=offset)

    text_msgs = []
    new_max_id = last_id
    for u in updates:
        uid = int(u.get('update_id', 0))
        if uid > new_max_id:
            new_max_id = uid
        msg = u.get('message') or u.get('edited_message')
        if not msg:
            continue
        if str(msg.get('chat', {}).get('id')) != str(TELEGRAM_CHAT_ID):
            continue
        text = msg.get('text')
        if not text:
            continue
        text_msgs.append(text)

    if not text_msgs:
        print('No new text messages to process.')
        if new_max_id > last_id:
            save_state({'last_update_id': new_max_id})
            print(f'Advanced last_update_id to {new_max_id} (no-text updates skipped).')
        return

    print(f'Processing {len(text_msgs)} new text message(s).')

    context_md = CONTEXT_FILE.read_text() if CONTEXT_FILE.exists() else ''
    system_prompt = build_system_prompt(context_md)
    user_content = build_user_content(text_msgs)

    plan_json_str = call_gemini(system_prompt, user_content)

    # Validate it parses
    try:
        plan = json.loads(plan_json_str)
    except json.JSONDecodeError as e:
        print(f'Gemini returned non-JSON: {plan_json_str[:500]}', file=sys.stderr)
        raise

    # Re-stringify pretty for the Gist (easier to diff)
    pretty = json.dumps(plan, indent=2)
    update_gist(pretty)
    print('plan.json updated in Gist.')

    save_state({'last_update_id': new_max_id})
    print(f'Advanced last_update_id to {new_max_id}.')

    send_telegram_message(
        "today's plan is ready 🌅\n"
        "open: https://abilash-augustus.github.io/daily-plan/"
    )
    print('Telegram confirmation sent.')


if __name__ == '__main__':
    main()
