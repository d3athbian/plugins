#!/usr/bin/env python3
"""Google Calendar MCP server (stdio) using the public Calendar API v3.

No developer-preview enrollment required. Auth: run bin/gcal_auth.py once;
tokens live in $CODEX_HOME/gcal_token.json (default ~/.codex/gcal_token.json)
and are refreshed automatically.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
TOKEN_PATH = os.path.join(CODEX_HOME, "gcal_token.json")
API = "https://www.googleapis.com/calendar/v3"
DEFAULT_CALENDAR = "primary"


def log_err(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def load_token():
    with open(TOKEN_PATH) as fh:
        data = json.load(fh)
    expires_at = data.get("expires_at", 0)
    if not expires_at or expires_at < time.time() + 60:
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=urllib.parse.urlencode(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": data["refresh_token"],
                    "client_id": data["client_id"],
                    "client_secret": data["client_secret"],
                }
            ).encode(),
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        data["access_token"] = resp["access_token"]
        data["expires_at"] = int(time.time()) + int(resp.get("expires_in", 3600))
        with open(TOKEN_PATH, "w") as fh:
            json.dump(data, fh, indent=1)
        os.chmod(TOKEN_PATH, 0o600)
    return data["access_token"]


def api(method, path, params=None, body=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": "Bearer " + load_token(), "Content-Type": "application/json"},
    )
    try:
        raw = urllib.request.urlopen(req, timeout=45).read()
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError("Google Calendar API %s: %s" % (exc.code, detail))


def when_text(node):
    if not node:
        return None
    return node.get("dateTime") or node.get("date")


def summarize_event(ev):
    out = {
        "eventId": ev.get("id"),
        "summary": ev.get("summary"),
        "start": when_text(ev.get("start")),
        "end": when_text(ev.get("end")),
        "status": ev.get("status"),
        "location": ev.get("location"),
        "hangoutLink": ev.get("hangoutLink"),
    }
    attendees = ev.get("attendees") or []
    if attendees:
        out["attendees"] = [a.get("email") for a in attendees]
    return {k: v for k, v in out.items() if v}


def t_list_calendars(args):
    resp = api("GET", "/users/me/calendarList", {"maxResults": args.get("pageSize", 50)})
    cals = [
        {
            "calendarId": c.get("id"),
            "summary": c.get("summary"),
            "primary": bool(c.get("primary")),
            "accessRole": c.get("accessRole"),
            "timeZone": c.get("timeZone"),
        }
        for c in resp.get("items", [])
    ]
    return {"calendars": cals, "totalItems": len(cals)}


def t_list_events(args):
    cal = urllib.parse.quote(args.get("calendarId") or DEFAULT_CALENDAR, safe="")
    params = {
        "timeMin": args.get("startTime"),
        "timeMax": args.get("endTime"),
        "q": args.get("fullText"),
        "maxResults": args.get("pageSize", 25),
        "orderBy": args.get("orderBy", "startTime"),
        "singleEvents": "true",
    }
    resp = api("GET", "/calendars/%s/events" % cal, params)
    events = [summarize_event(e) for e in resp.get("items", [])]
    return {"events": events, "totalItems": len(events)}


def t_get_event(args):
    cal = urllib.parse.quote(args.get("calendarId") or DEFAULT_CALENDAR, safe="")
    ev = api("GET", "/calendars/%s/events/%s" % (cal, urllib.parse.quote(args["eventId"], safe="")))
    return summarize_event(ev)


def t_search_events(args):
    args = dict(args)
    args["fullText"] = args.pop("query", None)
    return t_list_events(args)


def _event_body(args, partial=False):
    body = {}
    if not partial or args.get("summary") is not None:
        body["summary"] = args.get("summary")
    if args.get("description") is not None:
        body["description"] = args["description"]
    if args.get("location") is not None:
        body["location"] = args["location"]
    start, end = args.get("startTime"), args.get("endTime")
    if start or (not partial and args.get("summary")):
        if args.get("allDay"):
            body["start"] = {"date": start}
            body["end"] = {"date": end or start}
        else:
            tz = args.get("timeZone")
            if start:
                body["start"] = {"dateTime": start, "timeZone": tz} if tz else {"dateTime": start}
            if end:
                body["end"] = {"dateTime": end, "timeZone": tz} if tz else {"dateTime": end}
    emails = args.get("attendeeEmails")
    if emails:
        body["attendees"] = [{"email": e} for e in emails]
    return {k: v for k, v in body.items() if v is not None}


def t_create_event(args):
    cal = urllib.parse.quote(args.get("calendarId") or DEFAULT_CALENDAR, safe="")
    ev = api("POST", "/calendars/%s/events" % cal, body=_event_body(args))
    return summarize_event(ev)


def t_update_event(args):
    cal = urllib.parse.quote(args.get("calendarId") or DEFAULT_CALENDAR, safe="")
    path = "/calendars/%s/events/%s" % (cal, urllib.parse.quote(args["eventId"], safe=""))
    ev = api("PATCH", path, body=_event_body(args, partial=True))
    return summarize_event(ev)


def t_delete_event(args):
    cal = urllib.parse.quote(args.get("calendarId") or DEFAULT_CALENDAR, safe="")
    api("DELETE", "/calendars/%s/events/%s" % (cal, urllib.parse.quote(args["eventId"], safe="")))
    return {"deleted": True, "eventId": args["eventId"]}


def t_respond_to_event(args):
    cal = urllib.parse.quote(args.get("calendarId") or DEFAULT_CALENDAR, safe="")
    path = "/calendars/%s/events/%s" % (cal, urllib.parse.quote(args["eventId"], safe=""))
    body = {"responseStatus": args["responseStatus"]}
    if args.get("responseComment"):
        body["responseComment"] = args["responseComment"]
    ev = api("PATCH", path, body=body)
    return summarize_event(ev)


STR = {"type": "string"}
INT = {"type": "integer"}
CAL = {"type": "string", "description": "Calendar id; defaults to 'primary'."}

TOOLS = [
    {
        "name": "list_calendars",
        "description": "Lists the calendars of the signed-in Google account.",
        "inputSchema": {"type": "object", "properties": {"pageSize": INT}},
    },
    {
        "name": "list_events",
        "description": "Lists events on a calendar between optional startTime/endTime (RFC3339). Time constraints should only be specified when requested by the user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "calendarId": CAL,
                "startTime": STR,
                "endTime": STR,
                "fullText": {"type": "string", "description": "Free-text query filter."},
                "pageSize": INT,
                "orderBy": STR,
            },
        },
    },
    {
        "name": "get_event",
        "description": "Gets a single event by eventId.",
        "inputSchema": {
            "type": "object",
            "properties": {"calendarId": CAL, "eventId": STR},
            "required": ["eventId"],
        },
    },
    {
        "name": "search_events",
        "description": "Searches events by free-text query.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": STR, "calendarId": CAL, "pageSize": INT},
            "required": ["query"],
        },
    },
    {
        "name": "create_event",
        "description": "Creates a calendar event. startTime/endTime are RFC3339 datetimes unless allDay=true (then YYYY-MM-DD).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "calendarId": CAL,
                "summary": STR,
                "startTime": STR,
                "endTime": STR,
                "allDay": {"type": "boolean"},
                "timeZone": STR,
                "description": STR,
                "location": STR,
                "attendeeEmails": {"type": "array", "items": STR},
            },
            "required": ["summary", "startTime", "endTime"],
        },
    },
    {
        "name": "update_event",
        "description": "Updates fields of an existing event (only provided fields change).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "calendarId": CAL,
                "eventId": STR,
                "summary": STR,
                "startTime": STR,
                "endTime": STR,
                "timeZone": STR,
                "description": STR,
                "location": STR,
            },
            "required": ["eventId"],
        },
    },
    {
        "name": "delete_event",
        "description": "Deletes an event.",
        "inputSchema": {
            "type": "object",
            "properties": {"calendarId": CAL, "eventId": STR},
            "required": ["eventId"],
        },
    },
    {
        "name": "respond_to_event",
        "description": "Sets the user's RSVP on an event (accepted / declined / tentative).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "calendarId": CAL,
                "eventId": STR,
                "responseStatus": {"type": "string", "enum": ["accepted", "declined", "tentative"]},
                "responseComment": STR,
            },
            "required": ["eventId", "responseStatus"],
        },
    },
]

HANDLERS = {
    "list_calendars": t_list_calendars,
    "list_events": t_list_events,
    "get_event": t_get_event,
    "search_events": t_search_events,
    "create_event": t_create_event,
    "update_event": t_update_event,
    "delete_event": t_delete_event,
    "respond_to_event": t_respond_to_event,
}


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    if not os.path.exists(TOKEN_PATH):
        log_err("Missing %s — run bin/gcal_auth.py first (one-time Google OAuth)." % TOKEN_PATH)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": params.get("protocolVersion", "2025-03-26"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "google-calendar", "version": "1.3.0"},
                    },
                }
            )
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            name = params.get("name")
            handler = HANDLERS.get(name)
            if not handler:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {"content": [{"type": "text", "text": "Unknown tool: %s" % name}], "isError": True},
                    }
                )
                continue
            try:
                result = handler(params.get("arguments") or {})
                payload = json.dumps(result, ensure_ascii=False, indent=1)
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": payload}], "isError": False}})
            except Exception as exc:  # noqa: BLE001 - surface any error to the model
                log_err("%s: %s" % (name, exc))
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True},
                    }
                )
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": "Method not found: %s" % method},
                }
            )


if __name__ == "__main__":
    main()
