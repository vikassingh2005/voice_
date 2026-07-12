"""
llm.py — Local LLM brain via Ollama with native tool/function calling.

Features
────────
• Streaming generation: yields text tokens as they arrive so the TTS
  pipeline can begin synthesis without waiting for the full response.
• Native Ollama tool-calling: if the model decides to invoke a tool the
  call is intercepted, executed locally, and the result re-injected before
  the next streaming pass.
• Memory integration: retrieved facts are appended to the system prompt.

Public API
──────────
LLMEngine.stream_response(user_text: str, memory_context: str = "")
    -> Generator[str, None, None]
    Yields individual text tokens.  Tool calls are handled transparently;
    the generator may pause while a tool is executed, then resume with the
    model's follow-up text.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import ollama
from loguru import logger

import config


# ─────────────────────────────────────────────────────────────────────────────
# Tool schema definitions
# ─────────────────────────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "control_light",
            "description": (
                "Turn a smart-home light bulb on or off in a specified room."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": (
                            "The room whose light should be controlled, "
                            "e.g. 'living room', 'bedroom', 'kitchen'."
                        ),
                    },
                    "state": {
                        "type": "string",
                        "enum": ["on", "off"],
                        "description": "Whether to turn the light on or off.",
                    },
                },
                "required": ["room", "state"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Return the current local date and time.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────

def _tool_control_light(room: str, state: str) -> str:
    """Simulate toggling a Philips Hue (or any smart) light."""
    logger.info(f"[TOOL] control_light(room={room!r}, state={state!r})")
    # In a real deployment, integrate with Home Assistant / Hue API here.
    return json.dumps(
        {"success": True, "room": room, "state": state},
        ensure_ascii=False,
    )


def _tool_get_current_time() -> str:
    """Return the current local time as an ISO string."""
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    logger.info(f"[TOOL] get_current_time() -> {now}")
    return json.dumps({"current_time": now})


_TOOL_DISPATCH: dict[str, Any] = {
    "control_light": lambda args: _tool_control_light(**args),
    "get_current_time": lambda args: _tool_get_current_time(),
}


# ─────────────────────────────────────────────────────────────────────────────
# LLMEngine
# ─────────────────────────────────────────────────────────────────────────────

class LLMEngine:
    """
    Manages conversation history and Ollama API interaction.

    A single instance should be kept alive for the lifetime of the process
    so that conversation_history persists across turns.
    """

    def __init__(self) -> None:
        self._client = ollama.Client(host=config.OLLAMA_HOST)
        self._history: list[dict] = []

        # Verify connectivity
        try:
            self._client.list()
            logger.success(f"Connected to Ollama at {config.OLLAMA_HOST}.")
        except Exception as exc:
            logger.error(
                f"Cannot reach Ollama at {config.OLLAMA_HOST}: {exc}\n"
                "Ensure 'ollama serve' is running."
            )
            raise

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_system_prompt(self, memory_context: str) -> str:
        return config.SYSTEM_PROMPT + memory_context

    def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """Dispatch a tool call and return its result as a JSON string."""
        handler = _TOOL_DISPATCH.get(tool_name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            return handler(tool_args)
        except Exception as exc:
            logger.error(f"Tool {tool_name!r} raised: {exc}")
            return json.dumps({"error": str(exc)})

    # ──────────────────────────────────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────────────────────────────────

    def stream_response(
        self, user_text: str, memory_context: str = ""
    ) -> Generator[str, None, None]:
        """
        Stream LLM response tokens for user_text.

        Tool calls are handled transparently: execution happens here, and
        the model is prompted again with the tool result so it can generate
        a natural language follow-up.  All follow-up tokens are yielded as
        if they were part of the original stream.

        Parameters
        ----------
        user_text:
            The transcribed user utterance.
        memory_context:
            Formatted memory block from MemoryStore.build_context_block().
            May be an empty string.

        Yields
        ------
        str
            Individual text tokens from the model.
        """
        # Append user turn to history
        self._history.append({"role": "user", "content": user_text})

        messages = [
            {"role": "system", "content": self._build_system_prompt(memory_context)},
            *self._history,
        ]

        logger.debug(f"LLM ← user: {user_text!r}")

        # ── First streaming pass ─────────────────────────────────────────────
        full_assistant_text, tool_calls = yield from self._stream_once(messages)

        # ── Tool call loop ───────────────────────────────────────────────────
        # Models can request multiple tools in sequence; handle them all.
        while tool_calls:
            # Commit the assistant's (possibly empty) text + tool call intent
            # back into the conversation history so the model retains context.
            assistant_msg: dict = {"role": "assistant", "content": full_assistant_text}
            # Ollama expects tool_calls as part of the message when present
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"].get("arguments", {})
                if isinstance(fn_args, str):
                    try:
                        fn_args = json.loads(fn_args)
                    except json.JSONDecodeError:
                        fn_args = {}

                result = self._execute_tool(fn_name, fn_args)
                logger.debug(f"Tool result [{fn_name}]: {result}")

                messages.append(
                    {
                        "role": "tool",
                        "content": result,
                    }
                )

            # Re-prompt with tool results; collect any further text/tools
            full_assistant_text, tool_calls = yield from self._stream_once(messages)

        # Persist final assistant reply in conversation history
        self._history.append({"role": "assistant", "content": full_assistant_text})
        logger.debug(f"LLM → assistant: {full_assistant_text!r}")

    def _stream_once(
        self, messages: list[dict]
    ) -> Generator[str, None, tuple[str, list]]:
        """
        One streaming call to Ollama.

        Yields individual content tokens and, when the generator is
        exhausted, returns (full_text, tool_calls) via StopIteration.
        """
        accumulated_text = ""
        tool_calls: list = []

        try:
            stream = self._client.chat(
                model=config.OLLAMA_MODEL,
                messages=messages,
                tools=TOOLS,
                stream=True,
            )

            for chunk in stream:
                msg = chunk.get("message", {})

                # Text token
                delta = msg.get("content") or ""
                if delta:
                    accumulated_text += delta
                    yield delta

                # Tool call accumulation (may arrive across multiple chunks)
                if msg.get("tool_calls"):
                    tool_calls.extend(msg["tool_calls"])

        except ollama.ResponseError as exc:
            logger.error(f"Ollama error: {exc}")
            error_msg = "I'm sorry, I ran into a problem processing that."
            yield error_msg
            accumulated_text = error_msg

        return accumulated_text, tool_calls

    def reset_history(self) -> None:
        """Clear conversation history (start a fresh session)."""
        self._history.clear()
        logger.info("Conversation history cleared.")
