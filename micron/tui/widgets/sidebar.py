"""Sidebar widget for micron TUI."""
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, ListItem, ListView, Static, TabbedContent, TabPane


class Sidebar(Vertical):
    """Tabbed sidebar for memories, knowledge, skills, and sessions."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._memories: list = []
        self._knowledge: list = []
        self._skills: list = []
        self._sessions: list = []

    def compose(self):
        with TabbedContent():
            with TabPane("Memories", id="tab-memories"):
                yield Input(placeholder="Search memories...", id="memory-search")
                yield ListView(id="memory-list")
                yield Input(placeholder="Add memory...", id="memory-add")
            with TabPane("Knowledge", id="tab-knowledge"):
                yield Input(placeholder="Search knowledge...", id="knowledge-search")
                yield ListView(id="knowledge-list")
            with TabPane("Skills", id="tab-skills"):
                yield ListView(id="skill-list")
            with TabPane("Sessions", id="tab-sessions"):
                yield ListView(id="session-list")

    def on_mount(self):
        pass

    def set_memories(self, memories: list) -> None:
        self._memories = memories
        lv = self.query_one("#memory-list", ListView)
        lv.clear()
        for m in memories:
            text = getattr(m, "text", str(m))
            if len(text) > 40:
                text = text[:37] + "..."
            tags = getattr(m, "tags", [])
            importance = getattr(m, "importance", 3)
            tag_str = " ".join(f"[dim]#{t}[/dim]" for t in tags) if tags else ""
            imp_str = "●" * importance + "○" * (5 - importance)
            lv.append(ListItem(Static(f"{text}  [yellow]{imp_str}[/yellow]  {tag_str}")))

    def set_knowledge(self, docs: list) -> None:
        self._knowledge = docs
        lv = self.query_one("#knowledge-list", ListView)
        lv.clear()
        for doc in docs:
            text = getattr(doc, "title", str(doc))
            lv.append(ListItem(Static(text)))

    def set_skills(self, skills: list) -> None:
        self._skills = skills
        lv = self.query_one("#skill-list", ListView)
        lv.clear()
        for s in skills:
            name = getattr(s, "name", str(s))
            desc = getattr(s, "description", "")[:50]
            lv.append(ListItem(Static(f"[bold cyan]{name}[/bold cyan]: {desc}")))

    def set_sessions(self, sessions: list) -> None:
        self._sessions = sessions
        lv = self.query_one("#session-list", ListView)
        lv.clear()
        for s in sessions:
            sid = s.get("id", str(s))
            name = self._format_session_name(sid)
            turns = s.get("turns", 0)
            size = s.get("size", 0) // 1024
            lv.append(ListItem(Static(f"[cyan]{name}[/cyan]  {turns} turns  {size}KB")))

    @staticmethod
    def _format_session_name(sid: str) -> str:
        try:
            from datetime import datetime
            dt = datetime.strptime(sid, "%Y-%m-%d_%H%M%S")
            return dt.strftime("%b %-d, %H:%M")
        except (ValueError, TypeError):
            return sid[:12]

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "memory-search":
            self.post_message(self.SearchMemory(event.value))
        elif event.input.id == "memory-add":
            self.post_message(self.AddMemory(event.value))
            event.input.value = ""
        elif event.input.id == "knowledge-search":
            self.post_message(self.SearchKnowledge(event.value))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        list_view = event.control
        idx = list_view.index
        if list_view.id == "memory-list":
            if 0 <= idx < len(self._memories):
                self.post_message(self.MemorySelected(self._memories[idx]))
        elif list_view.id == "knowledge-list":
            if 0 <= idx < len(self._knowledge):
                self.post_message(self.KnowledgeSelected(self._knowledge[idx]))
        elif list_view.id == "skill-list":
            if 0 <= idx < len(self._skills):
                self.post_message(self.SkillSelected(self._skills[idx]))
        elif list_view.id == "session-list" and 0 <= idx < len(self._sessions):
            self.post_message(self.SessionSelected(self._sessions[idx]))

    class SearchMemory(Message):
        def __init__(self, query: str) -> None:
            super().__init__()
            self.query = query

    class AddMemory(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class MemorySelected(Message):
        def __init__(self, memory) -> None:
            super().__init__()
            self.memory = memory

    class SearchKnowledge(Message):
        def __init__(self, query: str) -> None:
            super().__init__()
            self.query = query

    class KnowledgeSelected(Message):
        def __init__(self, doc) -> None:
            super().__init__()
            self.doc = doc

    class SkillSelected(Message):
        def __init__(self, skill) -> None:
            super().__init__()
            self.skill = skill

    class SessionSelected(Message):
        def __init__(self, session: dict) -> None:
            super().__init__()
            self.session = session
