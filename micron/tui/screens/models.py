"""Model picker modal for the micron TUI."""
from typing import ClassVar

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import ListItem, ListView, Static

from micron.tui.commands import _format_price


def _model_detail(meta: dict) -> str:
    """One-line detail string for a model row."""
    parts: list[str] = []
    pricing = meta.get("pricing")
    if isinstance(pricing, dict) and pricing.get("prompt") is not None:
        prompt = _format_price(pricing.get("prompt"))
        completion = _format_price(pricing.get("completion"))
        parts.append(f"${prompt}/${completion} per M tok")
    ctx = meta.get("context_length")
    if isinstance(ctx, int) and ctx:
        if ctx >= 1_000_000 and ctx % 1_000_000 == 0:
            parts.append(f"{ctx // 1_000_000}m ctx")
        elif ctx % 1000 == 0:
            parts.append(f"{ctx // 1000}k ctx")
        else:
            parts.append(f"{ctx} ctx")
    params = meta.get("parameter_size")
    if params:
        parts.append(str(params))
    quant = meta.get("quantization_level")
    if quant:
        parts.append(str(quant))
    return " · ".join(parts)


class ModelPickerScreen(Screen):
    """Modal list of available models; click a row to switch.

    Fires :class:`ModelSelected` with the chosen ``(provider, model)`` so
    the app can perform the backend swap and refresh the status bar.
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def __init__(self, entries: list[tuple[str, str, dict]], **kwargs) -> None:
        super().__init__(**kwargs)
        self._entries = entries

    def compose(self):
        with Vertical(id="model-dialog"):
            yield Static("Select a model:", id="model-title")
            yield ListView(id="model-list")

    def on_mount(self) -> None:
        lv = self.query_one("#model-list", ListView)
        prov_w = max((len(p) for p, _, _ in self._entries), default=0)
        model_w = max((len(m) for _, m, _ in self._entries), default=0)
        for prov, model, meta in self._entries:
            detail = _model_detail(meta)
            label = f"{prov:<{prov_w}}  {model:<{model_w}}"
            if detail:
                label += f"  [{detail}]"
            lv.append(ListItem(Static(label)))
        lv.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if 0 <= idx < len(self._entries):
            prov, model, _meta = self._entries[idx]
            self.dismiss({"provider": prov, "model": model})
