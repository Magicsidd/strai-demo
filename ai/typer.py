from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Bilde:
    filnavn: str
    mediatype: str
    data: bytes


class AIBackend(Protocol):
    navn: str

    def fullfor(self, oppgave: str, system: str, bruker: str, bilder: list[Bilde], data: dict) -> str:
        """Returnerer modellens tekstsvar. `oppgave` er navnet på promptfila i ai/prompter
        (reklamasjon, tegnetime, ordresjekk eller avvik). `data` er inndata i strukturert form,
        brukt av den regelbaserte reserven som ikke leser prompten."""
        ...
