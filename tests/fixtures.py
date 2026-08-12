from __future__ import annotations

import json


CHAT_ROWS = (
    {
        "replayChatItemAction": {
            "videoOffsetTimeMsec": "0",
            "actions": [
                {
                    "clickTrackingParams": "system",
                    "addChatItemAction": {
                        "item": {
                            "liveChatViewerEngagementMessageRenderer": {
                                "id": "system-1",
                                "message": {
                                    "runs": [{"text": "Live chat replay is on."}]
                                },
                            }
                        }
                    },
                }
            ],
        }
    },
    {
        "replayChatItemAction": {
            "videoOffsetTimeMsec": "20485",
            "actions": [
                {
                    "clickTrackingParams": "text",
                    "addChatItemAction": {
                        "item": {
                            "liveChatTextMessageRenderer": {
                                "id": "message-1",
                                "authorExternalChannelId": "UCauthor1",
                                "authorName": {"simpleText": "First author"},
                                "message": {"runs": [{"text": "good morning"}]},
                            }
                        }
                    },
                }
            ],
        }
    },
    {
        "replayChatItemAction": {
            "videoOffsetTimeMsec": "1482532",
            "actions": [
                {
                    "clickTrackingParams": "emoji",
                    "addChatItemAction": {
                        "item": {
                            "liveChatTextMessageRenderer": {
                                "id": "message-2",
                                "authorExternalChannelId": "UCauthor2",
                                "authorName": {"simpleText": "Second author"},
                                "message": {
                                    "runs": [
                                        {
                                            "emoji": {
                                                "emojiId": "heart",
                                                "shortcuts": [":heart:"],
                                            }
                                        }
                                    ]
                                },
                            }
                        }
                    },
                }
            ],
        }
    },
)

CHAT_JSONL = "\n".join(
    json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in CHAT_ROWS
) + "\n"
