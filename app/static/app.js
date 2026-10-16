// Litt vanilla JS: eksempeldata, ventetilstand ved innsending, klikkbare rader og verktøytips.
const EKSEMPLER = {
  reklamasjon: {
    kundenavn: "Ingrid Haugland",
    epost: "ingrid.haugland@eksempel.no",
    ordrenummer: "SO-24830",
    butikk: "Strai Kristiansand",
    fritekst: "Skapet under vasken har begynt å svelle i bunnen, og sideveggen har løsnet litt. Det har vært en liten lekkasje fra vannlåsen som rørleggeren har fikset. Kjøkkenet ble montert i mai.",
  },
  tegnetime: {
    navn: "Thomas Eikeland",
    postnummer: "4631",
    epost: "thomas.eikeland@eksempel.no",
    telefon: "915 55 123",
    onsket_butikk: "",
    beskrivelse: "Vi skal pusse opp kjøkkenet fra 1998 og vil gjerne ha en kjøkkenøy. Håper å være ferdig før jul. Budsjett rundt 250 000 kr.",
  },
};

document.querySelectorAll("[data-eksempel]").forEach((knapp) => {
  knapp.addEventListener("click", () => {
    const skjema = knapp.closest("form");
    Object.entries(EKSEMPLER[knapp.dataset.eksempel]).forEach(([navn, verdi]) => {
      const felt = skjema.elements[navn];
      if (felt) felt.value = verdi;
    });
  });
});

document.querySelectorAll("[data-filer]").forEach((input) => {
  input.addEventListener("change", () => {
    const tekst = input.closest(".opplasting").querySelector("[data-filtekst]");
    const n = Math.min(input.files.length, 10);
    tekst.textContent = n ? `${n} ${n === 1 ? "bilde" : "bilder"} valgt` : "Opptil 10 bilder";
  });
});

document.querySelectorAll("[data-ai-skjema]").forEach((skjema) => {
  skjema.addEventListener("submit", () => {
    const jobber = skjema.querySelector(".jobber");
    jobber.classList.add("vis");
    skjema.querySelector("button[type=submit]").disabled = true;
    const steg = jobber.querySelectorAll("li");
    let i = 0;
    setInterval(() => {
      if (i < steg.length - 1) {
        steg[i].classList.remove("aktiv");
        steg[++i].classList.add("aktiv");
      }
    }, 2200);
  });
});

document.querySelectorAll("tr[data-href]").forEach((rad) => {
  rad.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    window.location = rad.dataset.href;
  });
});

const tips = document.querySelector(".tips");
if (tips) {
  document.addEventListener("mousemove", (e) => {
    const mal = e.target.closest("[data-tips]");
    if (!mal) return tips.classList.remove("vis");
    tips.textContent = mal.dataset.tips;
    tips.style.left = `${e.clientX + 14}px`;
    tips.style.top = `${e.clientY + 14}px`;
    tips.classList.add("vis");
  });
}

// Svarutkastet skal vises helt, uten intern rulling.
document.querySelectorAll("textarea.utkast").forEach((felt) => {
  const tilpass = () => {
    felt.style.height = "auto";
    felt.style.height = `${felt.scrollHeight + 2}px`;
  };
  felt.addEventListener("input", tilpass);
  tilpass();
});

// Skjema som endrer noe i Odoo, sendes bare én gang (ingen dobbel godkjenning ved dobbeltklikk).
document.querySelectorAll("form[data-en-gang]").forEach((skjema) => {
  skjema.addEventListener("submit", () => {
    skjema.querySelectorAll("button[type=submit]").forEach((knapp) => { knapp.disabled = true; });
  });
});
