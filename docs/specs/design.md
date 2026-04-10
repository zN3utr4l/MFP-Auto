# MFP Auto Bot - Design Spec

**Date**: 2026-04-10
**Status**: Draft
**Author**: g.chirico

## Overview

Bot Telegram che automatizza l'inserimento dei pasti su MyFitnessPal analizzando lo storico alimentare dell'utente per predire i pasti ricorrenti. Supporta multi-utente e account MFP sia Premium che free.

## Problem

Inserire manualmente ogni pasto su MFP e tedioso, specialmente per pasti ricorrenti (colazione, snack, bulk). Con 2+ anni di storico, la maggior parte dei pasti e prevedibile e potrebbe essere inserita automaticamente.

## Solution

Un bot Telegram che:
1. Analizza lo storico pasti dell'utente (scraping via python-myfitnesspal)
2. Predice i pasti giornalieri basandosi su pattern (giorno della settimana, slot, frequenza)
3. Propone i pasti con bottoni inline per confermare, cambiare o saltare
4. Inserisce i pasti confermati direttamente su MFP
5. Impara continuamente dalle conferme/modifiche dell'utente

## Tech Stack

- **Python 3.14** - ultima versione stabile (feature release corrente)
- **python-telegram-bot** (==22.7) - bot Telegram async con long-polling (Telegram Bot API 9.5)
- **myfitnesspal** (==2.1.2) - libreria non-ufficiale per leggere/scrivere su MFP
- **pandas** (>=2.2) - analisi pattern
- **cryptography** (>=44.0) - Fernet encryption per credenziali MFP
- **aiosqlite** (>=0.21) - SQLite async (compatibile con asyncio del bot)
- **SQLite** - storage locale, zero infrastruttura
- **PythonAnywhere** (free tier) - hosting always-on

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Telegram    │◄───►│   Bot Engine      │◄───►│  MFP Client │
│  (utente)    │     │  (orchestrator)   │     │  (python-   │
│              │     │                   │     │  myfitnesspal)
└─────────────┘     └────────┬─────────┘     └─────────────┘
                             │
                    ┌────────┴─────────┐
                    │   SQLite DB       │
                    │  - users          │
                    │  - meals_history  │
                    │  - meal_patterns  │
                    │  - week_progress  │
                    └──────────────────┘
```

3 componenti principali:
1. **Bot Engine** - orchestratore Telegram, gestisce comandi e callback inline
2. **Pattern Engine** - analizza storico + feedback continuo per generare predizioni
3. **MFP Client** - wrapper su `python-myfitnesspal` per leggere/scrivere pasti

## Meal Slots

7 slot personalizzati su MFP:

| # | Slot | Nome MFP | Prevedibilita |
|---|------|----------|---------------|
| 1 | breakfast | Breakfast | Alta (weekday vs weekend) |
| 2 | morning_snack | Morning Snack | Alta (bulk) |
| 3 | lunch | Lunch | Media/Bassa |
| 4 | afternoon_snack | Afternoon Snack | Alta (bulk) |
| 5 | pre_workout | Pre-Workout | Alta (bulk) |
| 6 | post_workout | Post-Workout | Alta (bulk) |
| 7 | dinner | Dinner | Media/Bassa |

## Pattern Engine

### Bootstrap iniziale

Percorso unico per tutti (Premium e free):
- **Scraping via `python-myfitnesspal`**: il bot scarica lo storico giorno per giorno. L'utente sceglie il range di date da importare.
- MFP non offre export CSV del diario (solo PDF non parsabile).

Dopo lo scraping, il bot chiede interattivamente di mappare i cibi "Snacks" ai 7 slot (solo per i cibi frequenti, >10 occorrenze). Quelli rari vengono classificati genericamente e imparati nel tempo.

### Predizione giornaliera

Per ogni slot + giorno della settimana:
- **Pasto fisso** (confidenza >70%): propone direttamente il default
- **Pasto variabile** (confidenza <70%): mostra top 3 alternative ordinate per frequenza recente

### Apprendimento continuo

Ad ogni interazione:
- Conferma -> peso +1
- Sostituzione -> nuovo pasto prende peso, vecchio perde
- **Decay temporale**: finestra mobile ~3 mesi. Pasti recenti pesano di piu. Se cambi abitudini per 3+ settimane, il sistema adatta i default.

## Bot Commands

| Comando | Azione |
|---------|--------|
| `/start` | Onboarding nuovo utente |
| `/login username password` | Registra credenziali MFP (messaggio cancellato subito) |
| `/import` | Scraping storico MFP (account free) |
| `/today` | Propone i 7 pasti di oggi |
| `/tomorrow` | Propone i 7 pasti di domani |
| `/week` | Wizard sequenziale: propone un giorno alla volta per 7 giorni |
| `/day Mon` | Propone i pasti di un giorno specifico |
| `/status` | Riepilogo settimana (inseriti/pendenti/saltati) |
| `/undo` | Rimuove l'ultimo pasto inserito su MFP |
| `/retry` | Reinserisce su MFP i pasti confermati ma non sincronizzati |
| `/import` | Ri-scrapa lo storico MFP (aggiorna pattern) |

## Interaction Flow

### `/today` e `/tomorrow`

```
Utente: /today

Bot: Mercoledi 10 Aprile

1. Breakfast
   Fiocchi d'avena 80g, Banana, Latte 200ml
   [Conferma] [Cambia] [Salta]

2. Morning Snack
   Mandorle 30g, Mela
   [Conferma] [Cambia] [Salta]

3. Lunch
   Variabile - scegli:
   [Pollo 200g + Riso 80g]
   [Tonno 160g + Insalata]
   [Pasta 80g + Ragu]
   [Cerca altro]

...per tutti i 7 slot
```

Bottoni:
- **Conferma** -> inserisce su MFP immediatamente
- **Cambia** -> mostra top 5 alternative dallo storico + "Cerca altro"
- **Salta** -> non inserisce (utente lo fara da app MFP, es. barcode)
- **Cerca altro** -> chiede nome cibo, cerca nel DB MFP, mostra risultati

### `/week`

Wizard sequenziale:
1. Mostra il primo giorno non ancora completamente inserito su MFP
2. Stessa interazione di `/today` (tutti i 7 slot, variabili inclusi)
3. Dopo la conferma dell'ultimo slot, passa automaticamente al giorno successivo
4. Bottone **[Stop - riprendo dopo]** disponibile in qualsiasi momento
5. Se interrotto, `/week` riprende da dove era rimasto
6. Timeout automatico dopo 30 minuti di inattivita (salva progresso)
7. Salta i giorni gia completamente inseriti
8. Se un giorno e parzialmente inserito, mostra solo gli slot mancanti

### Onboarding

```
Utente: /start

Bot: Ciao! Per iniziare serve il tuo account MyFitnessPal.
     Inviami le credenziali:
     /login username password
     (il messaggio viene cancellato subito per sicurezza)

Utente: /login mario rossi123

Bot: (cancella il messaggio)
     Connesso come mario su MFP!
     
     Da quanto tempo usi MFP? Quanti mesi di storico importo?
     [3 mesi] [6 mesi] [1 anno] [Tutto]

(Bot scrapa lo storico via python-myfitnesspal -> mapping snack interattivo)
(Scraping automatico via python-myfitnesspal)

Bot: Bootstrap completato!
     Pattern trovati: 47 | Alta confidenza: 12
     Prova /today per vedere i pasti di oggi!
```

## Data Model (SQLite)

### users
| Column | Type | Note |
|--------|------|------|
| telegram_user_id | INTEGER PK | Telegram user ID |
| mfp_username | TEXT | |
| mfp_password | TEXT | Encrypted (encryption key da env var) |
| is_premium | BOOLEAN | |
| onboarding_done | BOOLEAN | |
| created_at | TEXT | |

### meals_history
| Column | Type | Note |
|--------|------|------|
| id | INTEGER PK | |
| telegram_user_id | INTEGER FK | -> users |
| date | TEXT | YYYY-MM-DD |
| day_of_week | INTEGER | 0=Mon, 6=Sun |
| slot | TEXT | breakfast, morning_snack, lunch, ... |
| food_name | TEXT | |
| quantity | TEXT | "80g", "200ml", "1 unit" |
| mfp_food_id | TEXT | Per reinserimento su MFP |
| source | TEXT | mfp_scrape, bot_confirm, bot_search |
| created_at | TEXT | |

### meal_patterns
| Column | Type | Note |
|--------|------|------|
| id | INTEGER PK | |
| telegram_user_id | INTEGER FK | -> users |
| slot | TEXT | |
| day_type | TEXT | weekday, weekend, monday, tuesday, ... |
| food_combo | TEXT | JSON array dei cibi del pasto |
| mfp_food_ids | TEXT | JSON array degli ID MFP |
| weight | REAL | Score con decay temporale |
| last_confirmed | TEXT | Data ultima conferma |
| updated_at | TEXT | |

### week_progress
| Column | Type | Note |
|--------|------|------|
| id | INTEGER PK | |
| telegram_user_id | INTEGER FK | -> users |
| week_start | TEXT | YYYY-MM-DD |
| current_day | TEXT | YYYY-MM-DD, dove si e arrivato |
| status | TEXT | in_progress, completed, stopped |
| updated_at | TEXT | |

## Error Handling

**MFP non raggiungibile:**
- Pasti confermati salvati in `meals_history` comunque
- Bot avvisa: "Non riesco a inserire su MFP. Riprovo?" con [Riprova] [Salta]
- `/retry` reinserisce pasti confermati ma non sincronizzati

**Pasto duplicato:**
- Verifica se lo slot e gia popolato su MFP prima di inserire
- Se si: "Breakfast di oggi ha gia dei cibi su MFP. Sovrascrivo o salto?"

**Sessione Telegram inattiva:**
- Salva stato automaticamente dopo 30 minuti di inattivita
- `/week` riprende da dove era rimasto

**python-myfitnesspal si rompe:**
- Bot continua a funzionare per predizione/conferma
- Pasti confermati in coda locale
- `/retry` sincronizza quando la libreria torna operativa

## Project Structure

```
mfp-auto/
├── main.py                  # Entry point - avvia bot Telegram
├── requirements.txt         # Dipendenze
├── config.py                # Telegram token, encryption key (da env vars)
├── db/
│   ├── database.py          # Init SQLite, migrations
│   └── models.py            # Dataclass per le tabelle
├── bot/
│   ├── handlers.py          # Comandi Telegram (/today, /week, /status, ...)
│   ├── keyboards.py         # Bottoni inline e callback
│   └── messages.py          # Template messaggi e formattazione
├── mfp/
│   ├── client.py            # Wrapper su python-myfitnesspal (read/write)
│   ├── scraper.py           # Scraping storico MFP giorno per giorno
│   └── sync.py              # Logica retry e verifica duplicati
├── engine/
│   ├── pattern_analyzer.py  # Analisi storico, calcolo pesi, decay
│   ├── predictor.py         # Genera predizioni per giorno/slot
│   └── learner.py           # Aggiorna pesi post-conferma/modifica
└── data/                    # SQLite DB (auto-creato al primo avvio)
    └── mfp_auto.db
```

## Configuration

Environment variables:
- `TELEGRAM_BOT_TOKEN` - token dal BotFather
- `ENCRYPTION_KEY` - chiave per criptare credenziali MFP nel DB

Non serve piu `MFP_USERNAME` / `MFP_PASSWORD` globali: ogni utente registra le proprie credenziali via `/login`.

## Deployment (PythonAnywhere Free Tier)

1. Upload progetto su PythonAnywhere
2. `pip install -r requirements.txt`
3. Setta env vars dalla dashboard
4. Crea "Always-on task": `python main.py`
5. Rinnovare il free tier una volta ogni 3 mesi (reminder via email)

## Constraints & Risks

- **python-myfitnesspal non ufficiale**: puo rompersi se MFP cambia le API. Mitigato dal sistema di retry/coda locale.
- **PythonAnywhere free tier**: 1 always-on task, storage limitato. Sufficiente per questo uso.
- **Barcode scanning**: non supportato dal bot. L'utente usa l'app MFP nativa (bottone "Salta").
- **Rate limiting MFP**: lo scraping per account free potrebbe essere lento. Limiter integrato (max 1 request/secondo) per evitare ban.
- **Credenziali MFP**: salvate criptate nel DB con Fernet (symmetric encryption). Il messaggio `/login` viene cancellato subito dalla chat.
- **Slot personalizzati MFP**: la configurazione dei 7 slot su MFP va fatta manualmente dall'utente nella app (Premium feature). Il bot indica quali slot creare durante l'onboarding.
- **Decay formula**: peso = base_weight * 0.95^(settimane_passate). Dopo ~3 mesi (13 settimane) il peso e dimezzato.
