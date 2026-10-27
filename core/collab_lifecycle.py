"""Interpret explicit link lifecycle messages; counters are not lifecycle signals."""
def lifecycle_state(data):
    method = (data.get("common") or {}).get("method", "")
    kind = str(data.get("messageType", "")).upper()
    if method == "WebcastLinkMessage":
        if kind in {"2", "TYPE_LINKER_CLOSE"} or "closeContent" in data:
            return "solo", "linker_closed"
        content = data.get("linkedListChangeContent")
        if isinstance(content, dict) and isinstance(content.get("linkedUsers"), list):
            return ("collab", "linked_users_present") if content["linkedUsers"] else ("solo", "linked_users_empty")
        if kind in {"6", "TPYE_LINKER_ENTER", "TYPE_LINKER_ENTER"}:
            return "collab", "linker_entered"
    elif method == "WebcastLinkLayerMessage":
        if kind in {"10", "LINKER_FINISH"} or "finishContent" in data:
            return "solo", "channel_finished"
        content = data.get("listChangeContent") or {}
        roster = content.get("list") or {}
        if isinstance(roster.get("linkedList"), list):
            return ("collab", "linked_users_present") if roster["linkedList"] else ("solo", "linked_users_empty")
        if kind in {"12", "13", "LINKER_JOIN_DIRECT", "LINKER_JOIN_GROUP"}:
            return "collab", "linker_joined"
    return None, None


def redact_link_event(value):
    if isinstance(value, dict):
        return {k: ("[redacted]" if any(token in k.lower().replace("_", "")
                    for token in ("accesskey", "appsign", "sessionid", "rtcext", "token"))
                    else redact_link_event(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_link_event(v) for v in value]
    return value
