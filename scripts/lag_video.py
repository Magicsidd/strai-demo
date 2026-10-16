"""Tar opp en skriptet gjennomgang av demoen som video (docs/demo.mp4).

    .venv/bin/python scripts/lag_video.py

Krever: demoen kjørende på 127.0.0.1:8000 (./demo.sh), ekte Odoo for ordre (ORDRE_ODOO_* i .env),
Playwright (`uv pip install playwright` og `playwright install ffmpeg`), Google Chrome og ffmpeg.
Opptaket bruker ekte Claude. Det lager en fersk kopi av den usjekkede demoordren hver gang
(og fjerner forrige kopi), så skriptet kan kjøres flere ganger.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROT))

from app import odoo_ordre  # noqa: E402
from app.odoo_client import OdooClient, OdooKonfig  # noqa: E402
from demo.ordre_data import ORDRER  # noqa: E402
from demo.ordre_seed import USJEKKET  # noqa: E402

APP = "http://127.0.0.1:8000"
STORRELSE = {"width": 1440, "height": 900}
UT = ROT / "docs" / "demo.mp4"

# Tekststripe nederst og en synlig musepeker, lagt inn på hver side.
STIL = """
    #demo-tekst { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%); z-index: 99999;
      background: #ffffff; color: #231f20; border: 1px solid #bfb7ae; border-left: 4px solid #575441;
      border-radius: 5px; padding: 14px 22px; font: 400 20px/1.4 Sentient, Georgia, serif; max-width: 900px;
      box-shadow: 0 12px 32px -12px rgba(35,31,32,.35); transition: opacity .25s; }
    #demo-tekst small { display: block; font: 600 12px/1.4 Satoshi, -apple-system, sans-serif; letter-spacing: .1em;
      text-transform: uppercase; color: #7a7358; margin-bottom: 4px; }
    #demo-peker { position: fixed; width: 18px; height: 18px; border-radius: 50%; z-index: 99998;
      background: rgba(87,84,65,.3); border: 2px solid #575441; pointer-events: none;
      transform: translate(-50%, -50%); transition: left .12s, top .12s; left: -40px; top: -40px; }
"""

# Synlig musepeker, lagt inn på hver side.
OVERLEGG = """
(() => {
  const peker = document.createElement('div'); peker.id = 'demo-peker';
  document.addEventListener('mousemove', e => { peker.style.left = e.clientX + 'px'; peker.style.top = e.clientY + 'px'; });
  window.addEventListener('DOMContentLoaded', () => document.body.appendChild(peker));
})();
"""


def tekst(side: Page, steg: str, melding: str, sekunder: float = 3.5) -> None:
    side.evaluate("""([stil, steg, melding]) => {
        if (!document.getElementById('demo-stil')) {
            const s = document.createElement('style'); s.id = 'demo-stil'; s.textContent = stil;
            document.head.appendChild(s);
        }
        let t = document.getElementById('demo-tekst');
        if (!t) { t = document.createElement('div'); t.id = 'demo-tekst'; document.body.appendChild(t); }
        t.innerHTML = '<small>' + steg + '</small>' + melding;
    }""", [STIL, steg, melding])
    side.wait_for_timeout(int(sekunder * 1000))


def gaa_til(side: Page, url: str) -> None:
    side.goto(url)
    side.wait_for_timeout(900)  # inngangsanimasjonen på sidene tar rundt 0,6 sekunder


def flytt_og_klikk(side: Page, velger: str) -> None:
    boks = side.locator(velger).first.bounding_box()
    if boks:
        side.mouse.move(boks["x"] + boks["width"] / 2, boks["y"] + boks["height"] / 2, steps=12)
        side.wait_for_timeout(300)
    side.locator(velger).first.click()


def rull_til(side: Page, velger: str) -> None:
    side.locator(velger).first.scroll_into_view_if_needed()
    side.evaluate("window.scrollBy({top: 120, behavior: 'smooth'})")
    side.wait_for_timeout(700)


def fersk_ordre(odoo: OdooClient) -> int:
    """Fjerner forrige utgave av videoordren (med etterleveringer) og lager den på nytt som tilbud."""
    from datetime import date, datetime, timedelta

    kunde, butikk, modell, uker, onsker, linjer, _ = ORDRER[USJEKKET]
    gamle = odoo.search_read("sale.order", [("partner_id.name", "=", kunde)], ["id", "state"])
    for g in gamle:
        if g["state"] != "cancel" and isinstance(odoo.execute_kw("sale.order", "action_cancel", [[g["id"]]]), dict):
            odoo.write("sale.order", g["id"], {"state": "cancel"})
    if gamle:
        odoo.execute_kw("sale.order", "unlink", [[g["id"] for g in gamle]])
    ider = odoo_ordre.produkt_ider(odoo, [k for k, _ in linjer])
    levering = datetime.combine(date.today() + timedelta(weeks=uker), datetime.min.time()).replace(hour=10)
    return odoo.create("sale.order", {
        "partner_id": odoo.finn_eller_opprett_partner(kunde, f"{kunde.split()[0].lower()}@eksempel.no"),
        "x_type": "ordre", "x_butikk": butikk, "x_kjokkenmodell": modell, "x_kundens_onsker": onsker,
        "commitment_date": levering.strftime("%Y-%m-%d %H:%M:%S"),
        "order_line": [(0, 0, {"product_id": ider[k], "product_uom_qty": a}) for k, a in linjer]})


def main() -> int:
    odoo = OdooClient(OdooKonfig.fra_miljo("ORDRE_"))
    oid = fersk_ordre(odoo)
    stopp = odoo.search_read("sale.order", [("x_type", "=", "ordre"), ("x_kjokkenmodell", "=", "Trollstigen")],
                             ["id"], limit=1)[0]["id"]

    with tempfile.TemporaryDirectory() as mappe, sync_playwright() as pw:
        nettleser = pw.chromium.launch(channel="chrome", headless=True)
        kontekst = nettleser.new_context(viewport=STORRELSE, record_video_dir=mappe, record_video_size=STORRELSE,
                                         locale="nb-NO")
        kontekst.add_init_script(OVERLEGG)
        side = kontekst.new_page()

        gaa_til(side, f"{APP}/")
        tekst(side, "Riktig levert første gang", "En demo for Strai Kjøkken: AI i midten, Odoo som fasit, "
                    "et menneske som godkjenner.", 4.5)

        gaa_til(side, f"{APP}/ordre")
        tekst(side, "1 · Ordrene", "Butikkordrer i en ekte Odoo 18. Elementkodene er Strai sine, fra elementoversikten.")

        gaa_til(side, f"{APP}/ordre/{oid}")
        tekst(side, "2 · Før produksjon", "Ordren og kundens ønsker fra tegnetimen. Den er ikke sjekket ennå.")
        rull_til(side, ".onsker")
        tekst(side, "2 · Før produksjon", "Kunden ønsker eget skap til miksmaster. Står det på ordren?", 3)
        side.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        side.wait_for_timeout(600)
        flytt_og_klikk(side, "text=Kjør ordresjekk")
        tekst(side, "3 · Ordresjekk", "12 faste regler kjører først. Så sammenligner Claude ønskene med ordren.", 1)
        side.wait_for_url(f"**/ordre/{oid}", timeout=120_000)
        side.wait_for_selector(".funn", timeout=120_000)
        tekst(side, "3 · Ordresjekk", "Reglene fant for lite sokkel og en oppvaskmaskin uten dør. "
                    "Hvert funn har regel og sidetall.", 4.5)
        rull_til(side, ".funn >> nth=-1")
        tekst(side, "3 · Ordresjekk", "Claude fant miksmasterskapet, med ordrett sitat fra kunden og en gyldig kode "
                    "fra katalogen.", 5)

        rull_til(side, "input[name=begrunnelse]")
        side.locator("input[name=begrunnelse]").click()
        side.keyboard.type("Sokkel og dør er bestilt separat, bekreftet med kunden.", delay=18)
        tekst(side, "4 · Selger bestemmer", "Ordre med funn kan sendes videre, men bare med begrunnelse. "
                    "Den lagres i Odoo.", 2.5)
        flytt_og_klikk(side, "text=Overstyr og send til produksjon")
        side.wait_for_selector(".melding-ok", timeout=60_000)
        tekst(side, "4 · Selger bestemmer", "Ordren er bekreftet i Odoo, og leveransen er opprettet.", 3)

        rull_til(side, "textarea[name=melding]")
        side.locator("textarea[name=melding]").click()
        side.keyboard.type("Kolli 2 manglet. Vi har fått 5 håndtak, og sokkelen kom med knekt hjørne.", delay=18)
        tekst(side, "5 · Etter levering", "Montøren melder avvik med egne ord.", 2)
        flytt_og_klikk(side, "text=Registrer avvik")
        side.wait_for_url("**/avvik/*", timeout=120_000)
        tekst(side, "5 · Etter levering", "Claude koblet meldingen til ordrelinjene. Antallet kan aldri bli høyere "
                    "enn det som er bestilt.", 5)
        rull_til(side, "textarea.utkast")
        tekst(side, "5 · Etter levering", "Etterleveringen er en ny ordre i Odoo med saksnummer, og svarutkastet er "
                    "klart.", 4)

        flytt_og_klikk(side, "text=Kundens statusside")
        side.wait_for_load_state()
        tekst(side, "6 · Kunden", "Kunden får en statusside fra Odoo, med saksnummer.", 4)

        gaa_til(side, f"{APP}/ordre/{stopp}")
        tekst(side, "Et stopp", "Trollstigen kan ikke ha overskap, og maskinen er for dyp. Regelen siterer "
                    "modelloversikten.", 5)

        gaa_til(side, f"{APP}/dashbord")
        rull_til(side, "text=Ordre og levering")
        tekst(side, "7 · Tilbake til fabrikken", "Hvilke feil som stoppes før produksjon, og hvorfor avvik oppstår.", 5)

        side.goto(f"{odoo.konfig.url}/web/login")
        side.fill("input[name=login]", odoo.konfig.bruker)
        side.fill("input[name=password]", odoo.konfig.passord)
        side.locator("button[type=submit]").click()
        side.wait_for_url("**/odoo**", timeout=60_000)  # Odoo holder en tilkobling åpen, så vi venter på URL
        side.goto(f"{odoo.konfig.url}/odoo/sales/{oid}")
        side.wait_for_selector(".o_form_view", timeout=60_000)
        side.wait_for_timeout(1500)
        tekst(side, "Ekte Odoo", "Samme ordre i Odoo 18, med Strai sine elementkoder på ordrelinjene.", 4)
        chatter = side.locator(".o-mail-Chatter, .o-mail-Thread").first
        chatter.scroll_into_view_if_needed()
        side.wait_for_timeout(800)
        tekst(side, "Ekte Odoo", "Ordresjekken, begrunnelsen og avviket står i chatteren, synlig uten denne appen.", 6)

        gaa_til(side, f"{APP}/ai-logg")
        tekst(side, "Sporbarhet", "Hvert AI-kall logges med modell og promptversjon, uten kundens tekst. "
                    "Kode, tester og målinger ligger på GitHub.", 5)

        video = side.video.path()
        kontekst.close()
        nettleser.close()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-vf", "scale=1280:-2",
                        "-c:v", "libx264", "-crf", "28", "-preset", "slow", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(UT)], check=True)
    print(f"Skrev {UT} ({UT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    for linje in (ROT / ".env").read_text().splitlines() if (ROT / ".env").exists() else []:
        if "=" in linje and not linje.startswith("#"):
            navn, _, verdi = linje.partition("=")
            os.environ.setdefault(navn.strip(), verdi.strip())
    sys.exit(main())
