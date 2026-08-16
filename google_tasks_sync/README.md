# Home Assistant Add-on: Google Tasks Multi-Account Sync

Een complete Home Assistant Add-on om **Google Tasks automatisch te synchroniseren tussen meerdere Google Accounts** (bijv. Roy en Karen), met een moderne ingebouwde **Web UI (Ingress)** en een krachtige **Live JSON Editor**.

---

## Belangrijkste Functies

- 🔄 **Automatische Achtergrond Synchronisatie**: Houdt taken en lijsten continu synchroon tussen alle gekoppelde accounts op basis van een instelbaar interval (standaard elke 15 minuten).
- 👥 **Multi-Account Ondersteuning**: Koppel meerdere Google Accounts (Roy, Karen, Gezinsleden) via OAuth 2.0.
- 📋 **Live JSON Viewer & Editor**:
  - Bekijk direct de volledige JSON structuur van al je 13 lijsten en 150+ taken.
  - **1-klik Kopieerknop** naar je klembord.
  - **Download JSON** als `.json` backup bestand.
  - **Plak & Bewerk**: Bewerk de JSON direct in de editor en klik op **"Toepassen naar Google"** om alle wijzigingen direct live door te voeren.
  - **Syntax Validatie**: Controleert vooraf of je JSON 100% correct is om fouten te voorkomen.
- 📱 **Home Assistant Ingress Integratie**: Direct bereikbaar in je Home Assistant zijbalk op pc, tablet en de mobiele Home Assistant app.

---

## Installatie in Home Assistant

### Stap 1: Add-on map kopiëren naar Home Assistant
Kopieer de map `ha_addon_google_tasks_sync` naar de `/addons/` map van je Home Assistant installatie:
- Via de **Samba share** add-on: open de gedeelde map `addons` en sleep de map `ha_addon_google_tasks_sync` erin.
- Of via **SSH / Terminal**:
  ```bash
  cp -r /pad/naar/ha_addon_google_tasks_sync /addons/
  ```

### Stap 2: Add-on installeren
1. Ga in Home Assistant naar **Instellingen** -> **Add-ons** -> **Add-on Winkel** (rechtsonder).
2. Klik rechtsboven op de drie puntjes (`⋮`) en kies **Vernieuwen / Check for updates**.
3. Onder het kopje **Lokale add-ons** verschijnt nu **Google Tasks Multi-Account Sync**.
4. Klik op de add-on en klik op **Installeren**.

### Stap 3: Configuratie & Starten
1. Zet de schakelaars **Starten bij opstarten** en **In de zijbalk tonen** aan.
2. Kopieer je `client_secret.json` naar `/addon_configs/local_google_tasks_sync/client_secret.json` (of configureer deze via de Web UI).
3. Klik op **Starten**.
4. Klik op **Web-UI openen** in de zijbalk!

---

## Hoe Accounts Toe Te Voegen

1. Open de Web UI via de zijbalk van Home Assistant.
2. Ga naar het tabblad **Accounts Beheer**.
3. Je eerste account (Roy) is automatisch actief.
4. Klik op **+ Account Toevoegen** om Karen (of een extra account) toe te voegen met haar refresh token.
5. De synchronisatie gaat direct automatisch lopen!
