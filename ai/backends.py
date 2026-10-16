"""De tre AI-backendene bak samme grensesnitt (ai.typer.AIBackend)."""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile

from .regelbasert import RegelbasertBackend
from .typer import AIBackend, Bilde

MODELL = os.environ.get("AI_MODEL", "claude-sonnet-5-5")
STOTTEDE_BILDER = {"image/jpeg", "image/png", "image/gif", "image/webp"}


class AIFeil(RuntimeError):
    pass


class AnthropicBackend:
    """Claude via Anthropic API. Brukes når ANTHROPIC_API_KEY er satt. Sender bildene med."""

    navn = "anthropic"

    def __init__(self, modell: str = MODELL):
        import anthropic

        self.klient = anthropic.Anthropic()
        self.modell = modell

    def fullfor(self, oppgave: str, system: str, bruker: str, bilder: list[Bilde], data: dict) -> str:
        innhold: list[dict] = []
        for b in bilder[:10]:
            if b.mediatype in STOTTEDE_BILDER:
                innhold.append({"type": "image", "source": {
                    "type": "base64", "media_type": b.mediatype,
                    "data": base64.standard_b64encode(b.data).decode()}})
        innhold.append({"type": "text", "text": bruker})
        try:
            svar = self.klient.messages.create(
                model=self.modell, max_tokens=2000, system=system,
                messages=[{"role": "user", "content": innhold}])
        except Exception as feil:  # nettverk, kvote, ugyldig nøkkel
            raise AIFeil(f"Anthropic API feilet: {feil}") from feil
        return "".join(blokk.text for blokk in svar.content if blokk.type == "text")


class ClaudeCliBackend:
    """Claude Code CLI som subprocess: `claude -p <prompt> --output-format json`.

    Bruker innloggingen til Claude Code på maskinen, så ingen API-nøkkel trengs.
    Bilder sendes ikke i denne modusen, bare antallet nevnes i prompten.
    """

    navn = "claude_cli"

    def __init__(self, modell: str = MODELL, timeout: int = 180):
        self.bin = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
        self.modell = modell
        self.timeout = timeout

    def fullfor(self, oppgave: str, system: str, bruker: str, bilder: list[Bilde], data: dict) -> str:
        # Slankt kall: vår egen systemprompt, ingen verktøy, MCP, skills eller brukerinnstillinger.
        # Uten dette laster CLI-en hele Claude Code-oppsettet (rundt 75 000 tokens per kall).
        kommando = [self.bin, "-p", bruker, "--output-format", "json", "--model", self.modell,
                    "--system-prompt", system, "--tools", "", "--strict-mcp-config",
                    "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence"]
        # Egen tom mappe, så CLI-en ikke leser prosjektets CLAUDE.md eller filer.
        with tempfile.TemporaryDirectory() as mappe:
            try:
                kjoring = subprocess.run(kommando, capture_output=True, text=True,
                                         timeout=self.timeout, cwd=mappe)
            except FileNotFoundError as feil:
                raise AIFeil("Fant ikke `claude` i PATH.") from feil
            except subprocess.TimeoutExpired as feil:
                raise AIFeil(f"`claude -p` svarte ikke innen {self.timeout} sekunder.") from feil
        try:
            ytre = json.loads(kjoring.stdout)
        except json.JSONDecodeError as feil:
            raise AIFeil(f"Uventet svar fra `claude -p`: {kjoring.stdout[:200] or kjoring.stderr[:200]}") from feil
        if ytre.get("is_error"):
            raise AIFeil(f"`claude -p` feilet: {ytre.get('result', 'ukjent feil')}")
        return ytre.get("result", "")


class FastSvarBackend:
    """Returnerer ferdige svar. Brukes i tester."""

    navn = "fast"

    def __init__(self, svar: dict[str, str]):
        self.svar = svar

    def fullfor(self, oppgave: str, system: str, bruker: str, bilder: list[Bilde], data: dict) -> str:
        return self.svar[oppgave]


def velg_backend(navn: str | None = None) -> AIBackend:
    """AI_BACKEND = auto | anthropic | claude_cli | regelbasert.

    auto: anthropic hvis ANTHROPIC_API_KEY er satt, ellers claude_cli.
    """
    navn = (navn or os.environ.get("AI_BACKEND", "auto")).lower()
    if navn == "auto":
        navn = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "claude_cli"
    if navn == "anthropic":
        return AnthropicBackend()
    if navn == "claude_cli":
        return ClaudeCliBackend()
    if navn == "regelbasert":
        return RegelbasertBackend()
    raise ValueError(f"Ukjent AI_BACKEND: {navn}")
