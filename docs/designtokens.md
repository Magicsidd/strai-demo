# Strai Kjøkken: designtokens fra strai.no og beta.strai.no (lest 16.10.2026)

Kilde: offentlig CSS. strai.no = Umbraco + Bootstrap (`/css/Bootstrap/2022/Strai/init.min.css`).
beta.strai.no = Webflow (`strai-kjokken.shared.*.css`), trolig neste versjon av nettsiden.

## Farger
| Token | Verdi | Kilde |
|---|---|---|
| Tekst, hoved | `#231f20` | beta `--strai-brand-colors--textcolor-main` |
| Tekst, sterk | `#000` | begge |
| Bakgrunn | `#ffffff` | begge |
| Greige (merkevare-bakgrunn) | `#deddd5` | beta `--strai-brand-colors--lightgreen-background` |
| Varm lys beige | `#f1eeeb` (hoved), `#ebe7e7` / `#e6e5e2` (beta) | |
| Oliven (kampanje) | `#575441` | beta `--strai-base-colors--campaign-green` |
| Blågrå (primær i Bootstrap-tema) | `#4c677f` | strai.no `--primary` |
| Grønn (success) | `#2fa292` | strai.no `--success` |
| Rød (danger) | `#a12429` | strai.no `--danger` |
| Linjer | `#deddd5` (beta), `#dee2e6` (hoved), `rgba(0,0,0,.15)` | |
| System feil | bg `#f8e4e4`, tekst `#3b0b0b` | beta |
| System ok | bg `#cef5ca`, tekst `#114e0b` | beta |
| System varsel | bg `#fcf8d8`, tekst `#5e5515` | beta |

## Typografi
| Rolle | strai.no | beta.strai.no | Lisens for demo |
|---|---|---|---|
| Titler | Noto Serif Display 300/400/500 | Sentient, Butler, Domaine Display | Noto: Google Fonts (OFL). Sentient: Fontshare (gratis). Butler: gratis. Domaine: kommersiell, ikke bruk. |
| Brødtekst | Satoshi 400/500/700 | Satoshi 300 til 700 | Fontshare (gratis, også kommersielt) |
| Logo/merke | Halcom (Adobe Fonts, Strai sin lisens) | samme | IKKE bruk |
- Brødtekst 1.25rem (20 px), linjehøyde 1.5. `.h1` 3.125rem (50 px), vekt 500, linjehøyde 1.2.
- Lenker: svarte, understreket i toppmeny.

## Form
- Avrunding: 0 på strai.no (knapper og felt er helt firkantede). Beta: 5 px.
- Felt: tynn mørk ramme, hvit bakgrunn, ingen skygge.
- Store helsides kjøkkenbilder, mye luft, rolig og varm.

## Slik brukes de i demoen
- `app/static/stil.css` (`:root`): retning B, beta.strai.no. Varm beige bakgrunn, hvite flater, oliven som primærfarge, Sentient i titler og Satoshi i tekst (begge gratis fra Fontshare), 5 px avrunding.
- Varmekartene bruker en skala i Strai sin oliven.
- Logoen og Halcom brukes ikke. Demoen skal se ut som den hører hjemme hos Strai, men tydelig være en demo.
