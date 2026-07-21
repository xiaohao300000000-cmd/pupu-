from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FeishuTextMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    chat_type: str = Field(min_length=1)
    sender_open_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    create_time_ms: str | None = None


class LarkCliMessageEvent(BaseModel):
    """Flattened `lark-cli event consume im.message.receive_v1` output."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: str = "im.message.receive_v1"
    event_id: str | None = None
    message_id: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    chat_type: str = Field(min_length=1)
    sender_id: str = Field(min_length=1)
    message_type: str = Field(min_length=1)
    content: str
    create_time: str | None = None

    def to_text_message(self) -> FeishuTextMessage:
        if self.message_type != "text":
            raise ValueError("Feishu message is not plain text")
        return FeishuTextMessage(
            event_id=self.event_id or self.message_id,
            message_id=self.message_id,
            chat_id=self.chat_id,
            chat_type=self.chat_type,
            sender_open_id=self.sender_id,
            text=self.content,
            create_time_ms=self.create_time,
        )


class LarkCliCardActionEvent(BaseModel):
    """Flattened `lark-cli event consume card.action.trigger` output."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: str = "card.action.trigger"
    event_id: str = Field(min_length=1)
    timestamp: str
    operator_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    action_tag: str = Field(min_length=1)
    action_value: str = ""
    action_name: str = ""
    form_value: str = ""
    token: str = ""

    @model_validator(mode="after")
    def require_button_action_payload(self) -> LarkCliCardActionEvent:
        if self.action_tag == "button" and not (
            self.action_value or self.form_value
        ):
            raise ValueError("button callback has no action payload")
        return self

    def decoded_action_value(self) -> object:
        if not self.action_value:
            return None
        try:
            return json.loads(self.action_value)
        except json.JSONDecodeError:
            return self.action_value
