"""Tests for write tool confirmation flow."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from micron.agent import MicronAgent, AgentConfig, ToolCall
from micron.llm import LLMResponse


class FakeBackend:
    """Fake LLM backend for testing agent loops."""

    def __init__(self, responses: list[list[LLMResponse]]):
        self.responses = responses
        self.call_index = 0
        self.messages_history: list[list[dict]] = []

    def is_available(self) -> bool:
        return True

    def stream_chat(self, messages, tools=None, temperature=0.1, max_tokens=2048):
        self.messages_history.append([{"role": m["role"], **{k: m.get(k) for k in m if k != "role"}} for m in messages])
        if self.responses:
            responses = self.responses[self.call_index % len(self.responses)]
            self.call_index += 1
            yield from responses


def _write_tool_skill(tmpdir: Path):
    skill = tmpdir / "write_file.md"
    skill.write_text("""---
name: write_file
description: Write a file
write: true
module: micron.tools.builtin
parameters:
  type: object
  properties:
    path:
      type: string
    content:
      type: string
  required: [path, content]
---
""")


def make_confirmation_agent(tmpdir: Path, responses: list[list[LLMResponse]]):
    """Create an agent for testing confirmation flow."""
    ctx = tmpdir / "context"
    skills_dir = ctx / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    _write_tool_skill(skills_dir)

    backend = FakeBackend(responses)
    config = AgentConfig(
        context_dir=str(ctx),
        provider="fake",
        model="fake-model",
        llm_kwargs={"backend": backend},
    )
    agent = MicronAgent(config)
    agent.llm = backend
    return agent, backend


class TestConfirmationRequired:
    """Tests for confirmation_required event emission."""

    def test_write_tool_emits_confirmation_required(self):
        """Test that write tools emit confirmation_required event."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            old_workdir = os.environ.get("MICRON_WORKDIR")
            os.environ["MICRON_WORKDIR"] = str(tmpdir)
            
            try:
                agent, backend = make_confirmation_agent(
                    tmpdir,
                    [[
                        LLMResponse(type="tool_call", tool_name="write_file", tool_args={"path": "test.txt", "content": "hello"}, tool_call_id="call_1"),
                        LLMResponse(type="done"),
                    ]],
                )

                events = list(agent.run("write a file"))
                
                # Check that confirmation_required event is emitted
                confirmation_events = [e for e in events if e.get("type") == "confirmation_required"]
                assert len(confirmation_events) > 0
                
                # Check that pending_writes is populated
                assert "pending_writes" in confirmation_events[0]
                pending_writes = confirmation_events[0]["pending_writes"]
                assert len(pending_writes) > 0
                
                # Check that write_file is in pending writes
                tool_names = [w.get("tool_name") for w in pending_writes]
                assert "write_file" in tool_names
            finally:
                if old_workdir:
                    os.environ["MICRON_WORKDIR"] = old_workdir
                elif "MICRON_WORKDIR" in os.environ:
                    del os.environ["MICRON_WORKDIR"]

    def test_confirmation_required_contains_tool_details(self):
        """Test that confirmation_required event contains tool details."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            old_workdir = os.environ.get("MICRON_WORKDIR")
            os.environ["MICRON_WORKDIR"] = str(tmpdir)
            
            try:
                agent, backend = make_confirmation_agent(
                    tmpdir,
                    [[
                        LLMResponse(type="tool_call", tool_name="write_file", tool_args={"path": "test.txt", "content": "hello"}, tool_call_id="call_1"),
                        LLMResponse(type="done"),
                    ]],
                )

                events = list(agent.run("write a file"))
                
                confirmation_events = [e for e in events if e.get("type") == "confirmation_required"]
                assert len(confirmation_events) > 0
                
                pending_writes = confirmation_events[0]["pending_writes"]
                write_call = pending_writes[0]
                
                # Check that all required fields are present
                assert "tool_name" in write_call
                assert "args" in write_call
                assert "call_id" in write_call
                
                # Check values
                assert write_call["tool_name"] == "write_file"
                assert "path" in write_call["args"]
                assert "content" in write_call["args"]
            finally:
                if old_workdir:
                    os.environ["MICRON_WORKDIR"] = old_workdir
                elif "MICRON_WORKDIR" in os.environ:
                    del os.environ["MICRON_WORKDIR"]

    def test_tool_start_events_emitted(self):
        """Test that tool_start events are also emitted for write tools."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            old_workdir = os.environ.get("MICRON_WORKDIR")
            os.environ["MICRON_WORKDIR"] = str(tmpdir)
            
            try:
                agent, backend = make_confirmation_agent(
                    tmpdir,
                    [[
                        LLMResponse(type="tool_call", tool_name="write_file", tool_args={"path": "test.txt", "content": "hello"}, tool_call_id="call_1"),
                        LLMResponse(type="done"),
                    ]],
                )

                events = list(agent.run("write a file"))
                
                # Check for tool_start events
                tool_start_events = [e for e in events if e.get("type") == "tool_start"]
                assert len(tool_start_events) > 0
                
                # Check that write_file tool_start is present
                tool_names = [e.get("name") for e in tool_start_events]
                assert "write_file" in tool_names
            finally:
                if old_workdir:
                    os.environ["MICRON_WORKDIR"] = old_workdir
                elif "MICRON_WORKDIR" in os.environ:
                    del os.environ["MICRON_WORKDIR"]


class TestConfirmedWrites:
    """Tests for confirmed write execution."""

    def test_confirmed_write_executes(self):
        """Test that confirmed writes execute successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            old_workdir = os.environ.get("MICRON_WORKDIR")
            os.environ["MICRON_WORKDIR"] = str(tmpdir)
            
            try:
                agent, backend = make_confirmation_agent(tmpdir, [])

                pending = [
                    ToolCall(
                        name="write_file",
                        args={"path": "confirmed.txt", "content": "test content"},
                        call_id="call_confirm_1",
                        is_write=True,
                    )
                ]
                
                # Run with confirm=True
                events = list(agent.run("confirm write", confirm=True, pending_tool_calls=pending))
                
                # Check for tool_result event
                tool_result_events = [e for e in events if e.get("type") == "tool_result"]
                assert len(tool_result_events) > 0
                
                # Check that the write_file result is present
                assert tool_result_events[0].get("name") == "write_file"
            finally:
                if old_workdir:
                    os.environ["MICRON_WORKDIR"] = old_workdir
                elif "MICRON_WORKDIR" in os.environ:
                    del os.environ["MICRON_WORKDIR"]

    def test_confirmed_write_creates_file(self):
        """Test that confirmed writes actually create files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            old_workdir = os.environ.get("MICRON_WORKDIR")
            os.environ["MICRON_WORKDIR"] = str(tmpdir)
            
            try:
                agent, backend = make_confirmation_agent(tmpdir, [])

                pending = [
                    ToolCall(
                        name="write_file",
                        args={"path": "test_confirm.txt", "content": "confirmed content"},
                        call_id="call_confirm_2",
                        is_write=True,
                    )
                ]
                
                # Run with confirm=True
                events = list(agent.run("confirm write", confirm=True, pending_tool_calls=pending))
                
                # Check that the file was created
                test_file = tmpdir / "test_confirm.txt"
                assert test_file.exists()
                assert test_file.read_text() == "confirmed content"
            finally:
                if old_workdir:
                    os.environ["MICRON_WORKDIR"] = old_workdir
                elif "MICRON_WORKDIR" in os.environ:
                    del os.environ["MICRON_WORKDIR"]


class TestCancelledWrites:
    """Tests for cancelled write operations."""

    def test_cancelled_write_no_confirmation(self):
        """Test that writes without confirmation don't execute."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            old_workdir = os.environ.get("MICRON_WORKDIR")
            os.environ["MICRON_WORKDIR"] = str(tmpdir)
            
            try:
                agent, backend = make_confirmation_agent(
                    tmpdir,
                    [[
                        LLMResponse(type="tool_call", tool_name="write_file", tool_args={"path": "cancelled.txt", "content": "should not appear"}, tool_call_id="call_cancel"),
                        LLMResponse(type="done"),
                    ]],
                )
                
                # Run WITHOUT confirm=True (default is False)
                events = list(agent.run("write a file"))
                
                # Should emit confirmation_required, not execute
                confirmation_events = [e for e in events if e.get("type") == "confirmation_required"]
                assert len(confirmation_events) > 0
                
                # File should NOT be created
                cancelled_file = tmpdir / "cancelled.txt"
                assert not cancelled_file.exists()
            finally:
                if old_workdir:
                    os.environ["MICRON_WORKDIR"] = old_workdir
                elif "MICRON_WORKDIR" in os.environ:
                    del os.environ["MICRON_WORKDIR"]
