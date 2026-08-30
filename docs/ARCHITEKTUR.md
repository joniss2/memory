# Architekturentwurf

## Memory-Layer mit Herkunftsspur

**Arbeitstitel:** `provenance` · **Stand:** 30. August 2026 · **Status:** Entwurf zur Diskussion

> Dies ist der Entwurf, den die Umsetzung in diesem Repository beantwortet.
> Er wird unverändert mitgeführt, damit nachvollziehbar bleibt, wogegen
> gebaut wurde. Wo die Umsetzung abweicht, steht das begründet im
> [README](../README.md), Abschnitt „Abweichungen vom Entwurf".

---

Ein Container. Eine Datenbank. Jede Erinnerung erklärt sich selbst.

---

## 1. Zielbild

Ein selbst gehosteter Gedächtnis-Layer für LLM-Agenten, der drei Dinge
zusammenbringt, die heute auf drei Produkte verteilt sind:

| Funktion | Heute | Hier |
| --- | --- | --- |
| Fakten speichern und abrufen | mem0, Zep, Cognee | eingebaut |
| Nachvollziehen, warum etwas erinnert wurde | nirgends | Kernfunktion |
| DSGVO-Auskunft und -Löschung | manuell | dieselbe Datenstruktur |

Die zentrale These: **Herkunftsspur und Auditlog sind dasselbe Artefakt.** Wer
nachvollziehen kann, warum ein Agent einen Fakt erinnert hat, kann auch
beantworten, woher dieser Fakt stammt und was bei seiner Löschung mitgeht.

### Abgrenzung

Dies ist *kein* Framework für Agenten-Orchestrierung, kein RAG-System für
Dokumente und kein Observability-Aufsatz über fremde Memory-Layer. Es ist der
Gedächtnis-Layer selbst — weil Löschgarantien nur geben kann, wer die Daten
besitzt.

---

## 2. Prinzipien

**Ein Prozess, eine Datenbank.** Postgres mit `pgvector`. Kein Neo4j, kein
Qdrant, kein Redis. Der Graph sind zwei Tabellen und ein rekursives CTE. Bei
realistischen Größenordnungen — einige tausend Knoten pro Nutzer — löst eine
Graphdatenbank Probleme, die hier nicht existieren, und erkauft das mit
Betriebsaufwand, der sehr wohl existiert.

**Jede Erinnerung trägt ihre Herkunft.** Kein Fakt ohne Verweis auf den Turn,
aus dem er stammt, und auf die Entscheidung, die ihn erzeugt, verändert oder
verworfen hat. Herkunft ist eine Fremdschlüsselbeziehung, kein Logfile.

**Nichts wird überschrieben.** Fakten werden ungültig gesetzt, nicht ersetzt.
Der Zustand des Gedächtnisses zu jedem beliebigen Zeitpunkt ist
rekonstruierbar. Das ist die Voraussetzung für Replay, für Regressionstests
und für die Frage „was wusste das System am 14. Mai?".

**Die Eval ist Teil des Produkts.** Nicht Anhang, nicht Nice-to-have. Siehe
Abschnitt 9 — sie ist der Grund, warum dieses System besser sein kann statt
nur schlanker.

---

## 3. Systemüberblick

```
┌─────────────────────────────────────────────────────┐
│  Ein Container                                       │
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌───────────────┐ │
│  │ HTTP-API   │  │ MCP-Server │  │  Dashboard    │ │
│  └─────┬──────┘  └─────┬──────┘  └───────┬───────┘ │
│        └───────────────┴─────────────────┘         │
│                        │                            │
│        ┌───────────────▼───────────────┐           │
│        │   Pipeline                     │           │
│        │   1 Extraktion                 │           │
│        │   2 Konsolidierung             │           │
│        │   3 Retrieval                  │           │
│        │   4 Injection                  │           │
│        └───────────────┬───────────────┘           │
│                        │  jede Stufe schreibt Trace │
│        ┌───────────────▼───────────────┐           │
│        │   Postgres + pgvector          │           │
│        └───────────────────────────────┘           │
└─────────────────────────────────────────────────────┘
                         │
                  LLM-Anbindung
        (OpenAI-kompatibel · Ollama · vLLM)
```

Die LLM-Anbindung ist die einzige externe Abhängigkeit — und mit Ollama oder
vLLM lokal auflösbar. Das ist die Bedingung dafür, dass „souverän betreibbar"
nicht nur eine Behauptung ist.

---

## 4. Datenmodell

Sieben Tabellen. Der Graph ist keine Sonderwelt, sondern eine Projektion über
denselben Fakten.

### 4.1 Rohmaterial

```sql
CREATE TABLE turns (
  id          BIGSERIAL PRIMARY KEY,
  subject_id  TEXT NOT NULL,        -- die Person, um die es geht
  session_id  TEXT NOT NULL,
  role        TEXT NOT NULL,        -- user | assistant
  content     TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON turns (subject_id, occurred_at);
```

`subject_id` ist bewusst nicht `user_id`: Die Person, über die etwas
gespeichert wird, ist datenschutzrechtlich die betroffene Person. Die gesamte
Löschmechanik hängt an dieser Spalte.

### 4.2 Fakten — bitemporal

```sql
CREATE TYPE fact_status AS ENUM ('active', 'superseded', 'retracted', 'erased');

CREATE TABLE facts (
  id            BIGSERIAL PRIMARY KEY,
  subject_id    TEXT NOT NULL,
  content       TEXT NOT NULL,
  embedding     VECTOR(1024),
  status        fact_status NOT NULL DEFAULT 'active',
  -- Gültigkeitszeit: seit wann gilt das in der Welt?
  valid_from    TIMESTAMPTZ NOT NULL,
  valid_to      TIMESTAMPTZ,
  -- Transaktionszeit: seit wann weiß das System davon?
  recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  invalidated_at TIMESTAMPTZ,
  confidence    REAL,
  origin_turn   BIGINT REFERENCES turns(id)
);
CREATE INDEX ON facts USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON facts (subject_id, status);
```

Die Trennung von Gültigkeits- und Transaktionszeit ist der Unterschied
zwischen „er ist seit März Vegetarier" und „wir wissen seit Mai, dass er seit
März Vegetarier ist". Ohne diese Trennung ist weder Replay noch eine ehrliche
Auskunft möglich.

### 4.3 Abstammung — das Kernstück

```sql
CREATE TYPE decision AS ENUM ('add', 'update', 'retract', 'noop', 'merge');

CREATE TABLE lineage (
  id           BIGSERIAL PRIMARY KEY,
  fact_id      BIGINT NOT NULL REFERENCES facts(id),
  parent_id    BIGINT REFERENCES facts(id),   -- NULL bei 'add'
  op           decision NOT NULL,
  rationale    TEXT,                          -- Begründung des Modells
  trace_id     BIGINT NOT NULL REFERENCES traces(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON lineage (fact_id);
CREATE INDEX ON lineage (parent_id);
```

Diese Tabelle beantwortet drei Fragen, die heute niemand beantworten kann:

- Warum weiß das System das? → über `origin_turn` und `rationale`
- Was ist mit dem alten Wert passiert? → Kette über `parent_id`
- Was muss bei einer Löschung mit weg? → transitive Hülle über `parent_id`

### 4.4 Graph — zwei Tabellen, keine Graphdatenbank

```sql
CREATE TABLE entities (
  id          BIGSERIAL PRIMARY KEY,
  subject_id  TEXT NOT NULL,
  name        TEXT NOT NULL,
  kind        TEXT,                  -- person | ort | organisation | ...
  embedding   VECTOR(1024),
  UNIQUE (subject_id, name, kind)
);

CREATE TABLE edges (
  id          BIGSERIAL PRIMARY KEY,
  subject_id  TEXT NOT NULL,
  src         BIGINT NOT NULL REFERENCES entities(id),
  predicate   TEXT NOT NULL,
  dst         BIGINT NOT NULL REFERENCES entities(id),
  fact_id     BIGINT NOT NULL REFERENCES facts(id),   -- jede Kante hat einen Beleg
  valid_from  TIMESTAMPTZ NOT NULL,
  valid_to    TIMESTAMPTZ
);
CREATE INDEX ON edges (src) WHERE valid_to IS NULL;
CREATE INDEX ON edges (dst) WHERE valid_to IS NULL;
```

Entscheidend ist `edges.fact_id`: **Es gibt keine Kante ohne belegenden
Fakt.** Damit erbt der Graph die gesamte Herkunfts- und Löschmechanik, statt
eine zweite Wahrheit zu werden. Genau hier scheitern Systeme mit separater
Graphdatenbank an Art. 17 — der Vektorspeicher wird geleert, der Graph behält
die Beziehung.

Zwei-Hop-Nachbarschaft, ohne Cypher:

```sql
WITH RECURSIVE neighbourhood AS (
    SELECT e.dst AS node, 1 AS hop
    FROM edges e
    WHERE e.src = $1 AND e.valid_to IS NULL
  UNION
    SELECT e.dst, n.hop + 1
    FROM edges e
    JOIN neighbourhood n ON e.src = n.node
    WHERE e.valid_to IS NULL AND n.hop < 2
)
SELECT DISTINCT node FROM neighbourhood;
```

### 4.5 Traces

```sql
CREATE TYPE trace_kind AS ENUM ('write', 'read');

CREATE TABLE traces (
  id          BIGSERIAL PRIMARY KEY,
  subject_id  TEXT NOT NULL,
  kind        trace_kind NOT NULL,
  turn_id     BIGINT REFERENCES turns(id),
  query       TEXT,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  duration_ms INTEGER
);

CREATE TABLE trace_steps (
  id          BIGSERIAL PRIMARY KEY,
  trace_id    BIGINT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
  stage       SMALLINT NOT NULL,     -- 1..4
  model       TEXT,
  prompt_ref  TEXT,                  -- Version des Prompt-Templates
  input       JSONB,
  output      JSONB,
  duration_ms INTEGER,
  tokens_in   INTEGER,
  tokens_out  INTEGER
);
```

`prompt_ref` ist die Versionskennung des Prompt-Templates. Ohne sie ist ein
Trace von vor drei Wochen nicht interpretierbar, weil niemand mehr weiß,
welche Extraktionsanweisung damals galt.

---

## 5. Die vier Stufen

### Stufe 1 — Extraktion

**Eingang:** neuer Turn plus die letzten *n* Turns als Kontext.
**Ausgang:** Kandidatenfakten mit Gültigkeitszeitpunkt und Konfidenz.
**Trace:** vollständiger Prompt-Ref, rohe Modellantwort, verworfene Kandidaten
samt Grund.

Der wichtigste Trace-Punkt im ganzen System. Wenn ein Agent etwas „vergessen"
hat, wurde es meist hier nie extrahiert — aber debuggt wird traditionell
Stufe 3. Die Entwickleransicht zeigt darum standardmäßig Stufe 1, nicht
Stufe 3.

Explizit mitgeschrieben werden auch **Nicht-Extraktionen**: Sätze, die das
Modell als faktenfrei eingestuft hat. Ein leerer Extraktionsschritt ist ein
Befund, keine Leerstelle.

### Stufe 2 — Konsolidierung

**Eingang:** Kandidatenfakt plus die *k* ähnlichsten bestehenden Fakten.
**Ausgang:** eine Entscheidung — `add`, `update`, `retract`, `noop`, `merge` —
mit Begründung.
**Trace:** Kandidatenmenge mit Ähnlichkeitswerten, Entscheidung, Begründung,
Schreibvorgang in `lineage`.

Hier bricht jedes System, und hier misst niemand. Der klassische Fehlerfall:
„ich bin Vegetarier" wird drei Monate später durch „habe für die Kollegen
Burger bestellt" stillschweigend zurückgezogen, weil die Ähnlichkeit hoch und
die Begründung plausibel klang.

Zwei Härtungen gegenüber dem üblichen Vorgehen:

1. **Widerspruch ist ein eigener Ausgang, keine stille Überschreibung.** Bei
   erkanntem Konflikt wird der alte Fakt auf `superseded` gesetzt und bleibt
   abrufbar — mit Zeitstempel und Begründung.
2. **Rückzug erfordert höhere Konfidenz als Hinzufügen.** Vergessen ist teurer
   als Erinnern; die Schwelle ist asymmetrisch.

### Stufe 3 — Retrieval

Hybrid, mit Reciprocal Rank Fusion über drei Kandidatenquellen:

| Quelle | Mechanik | Stärke |
| --- | --- | --- |
| Vektor | Kosinus über `facts.embedding` | Paraphrasen |
| Volltext | Postgres `tsvector` | Eigennamen, Zahlen |
| Graph | rekursives CTE ab erkannten Entitäten | mehrstufige Bezüge |

Alle drei laufen in Postgres — kein Netzwerk-Hop, eine Transaktion, ein
konsistenter Zeitpunkt. Der Trace hält für jeden Kandidaten fest, aus welcher
Quelle er kam, mit welchem Rang und wie die Fusion ihn platziert hat.

### Stufe 4 — Injection

**Eingang:** gerankte Kandidaten, Token-Budget.
**Ausgang:** der tatsächlich in den Prompt gestellte Text.
**Trace:** was wegen Budgetgrenze herausgefallen ist.

Meist übersehen, regelmäßig schuldig: Ein Fakt kann korrekt extrahiert,
korrekt gespeichert und korrekt gefunden worden sein — und fällt an Rang 9 aus
dem Budget. Ohne diesen Trace-Punkt sucht man den Fehler an drei falschen
Stellen.

---

## 6. Dashboard — ein Datenmodell, zwei Ansichten

### Entwickleransicht

- **Turn-Zeitleiste** mit der Zustandsänderung je Turn: was kam dazu, was
  wurde zurückgezogen, was war ein No-op
- **Trace-Inspektor**: alle vier Stufen aufklappbar, Prompt-Version sichtbar,
  Kandidaten mit Rängen
- **Graph-Ansicht** mit Zeitschieber — Kantenklick zeigt den belegenden Fakt
  und den Ursprungs-Turn
- **Replay**: eine gespeicherte Session gegen geänderte Prompts oder Parameter
  erneut laufen lassen und das Ergebnis diffen

### Auskunftsansicht

- **Was wissen wir über Person X** — alle aktiven Fakten mit Quelle und
  Zeitstempel, exportierbar
- **Historie eines Fakts** — Kette über `lineage`, lesbar dargestellt
- **Löschen mit Vorschau** — welche Fakten, Kanten und abgeleiteten Einträge
  betroffen sind, *bevor* gelöscht wird

Dieselben Tabellen, andere Sprache. Die Auskunftsansicht enthält keine
Modell-Interna — sie zeigt Fakten, Quellen und Zeitpunkte.

---

## 7. Löschung

Löschung ist der Punkt, an dem sich Architekturen entscheiden. Der Ablauf:

1. Ermittle die transitive Hülle über `lineage.parent_id` — alle Fakten, die
   aus dem zu löschenden abgeleitet wurden
2. Zeige die Vorschau
3. Setze `facts.status = 'erased'`, leere `content` und `embedding`, behalte
   die Zeile
4. Setze `edges.valid_to`, wo `fact_id` betroffen ist
5. Schwärze die betroffenen `trace_steps` — `input`/`output` werden nach
   Schema geleert, Zeitstempel und Struktur bleiben
6. Schreibe einen Löschbeleg

Die leere Zeile bleibt bewusst stehen: Sie belegt, dass gelöscht wurde. Ein
spurloses `DELETE` kann man einer Aufsichtsbehörde nicht vorzeigen.

---

## 8. Schnittstellen

```
POST /v1/turns          Turn aufnehmen, Pipeline 1–2 auslösen
GET  /v1/recall         Abruf, Pipeline 3–4
GET  /v1/traces/:id     vollständiger Trace
GET  /v1/subjects/:id/export   DSGVO-Auskunft
POST /v1/subjects/:id/erase    Löschung mit Vorschau
```

MCP-Server mit denselben Operationen als Tools, damit das Gedächtnis ohne
Integrationsarbeit an beliebigen Assistenten hängt.

---

## 9. Die Eval — der eigentliche Hebel

Der Standard-Benchmark des Feldes (LoCoMo) hat zwei bekannte Schwächen: Die
Konversationen passen mit 16.000 bis 26.000 Token in gängige Kontextfenster —
ein simpler Full-Context-Baseline schlägt mem0 dort — und
**Wissensaktualisierung wird gar nicht getestet.** Genau die Stufe, die in
jedem System bricht.

Da nicht hinterherlaufen. Stattdessen die fehlende Eval bauen.

### Aufbau

Skriptgeführte Sitzungen, in denen sich Fakten planmäßig ändern, mit
Prüffragen an definierten Kontrollpunkten:

| Muster | Beispiel |
| --- | --- |
| Ersetzung | „Ich wohne in Köln" → sechs Monate später „bin nach Leipzig gezogen" |
| Verfeinerung | „Ich mag Kaffee" → „nur Filterkaffee, keinen Espresso" |
| Befristung | „Ich bin gerade in Elternzeit" |
| Scheinwiderspruch | „Bin Vegetarier" → „habe Burger bestellt" *(für Kollegen)* |
| Widerruf | „Vergiss, was ich über meinen Arbeitgeber gesagt habe" |

### Kennzahlen

- **Update Recall** — kennt das System nach der Änderung den neuen Wert?
- **Stale Rate** — liefert es weiterhin den alten? *Die Kennzahl, die heute
  niemand ausweist.*
- **False Retraction** — hat ein Scheinwiderspruch einen korrekten Fakt
  gekillt?
- **Erasure Completeness** — ist nach einer Löschung wirklich alles
  Abgeleitete weg?

`Stale Rate` und `False Retraction` sind der Kern der Positionierung. Sie
messen genau das, was die Herkunftsspur sichtbar macht — und was
Konkurrenzsysteme architektonisch nicht zeigen können, weil sie überschreiben
statt zu versionieren.

---

## 10. Risiken

**Qualität schlägt Betriebsvorteil.** Wenn das System spürbar schlechter
erinnert als mem0, rettet kein Auditlog. Die Extraktions- und
Konsolidierungs-Prompts sind das Produkt — die schlanke Ablage ist nur die
Voraussetzung dafür, dass man sie in Ruhe verbessern kann. *Gegenmaßnahme:
Eval vor Feature-Ausbau.*

**Trace-Volumen.** Vollständige Traces sind größer als die Fakten. Bei
täglichem Betrieb wächst `trace_steps` schnell. *Gegenmaßnahme: gestufte
Aufbewahrung — Traces nach 30 Tagen auf Metadaten reduzieren, Lineage
unbefristet halten.*

**Zwei Personas, ein Produkt.** Wenn beide Ansichten gleichzeitig gebaut
werden, wird keine gut. *Gegenmaßnahme: zuerst die Ansicht, für die echte
Nutzer erreichbar sind.*

**Kosten.** Zwei LLM-Aufrufe pro Turn ist der Stand der Technik, aber teuer.
*Gegenmaßnahme: Stufe 1 mit einem kleinen lokalen Modell, Stufe 2 nur bei
Ähnlichkeitstreffern oberhalb einer Schwelle.*

---

## 11. Schnitt für den ersten lauffähigen Stand

Reihenfolge nach Erkenntnisgewinn, nicht nach Vollständigkeit.

1. Schema, Stufen 1–2, Traces, keine Oberfläche — nur CLI
2. Eval-Suite mit zwanzig Änderungsszenarien. **Vor** dem Retrieval.
3. Stufe 3–4 hybrid, gegen die Eval optimiert
4. Entwickleransicht: Zeitleiste und Trace-Inspektor
5. MCP-Server
6. Graph-Ansicht mit Zeitschieber
7. Auskunftsansicht und Löschmechanik

Schritt 2 vor Schritt 3 ist die wichtigste Entscheidung in dieser Liste. Ohne
Messlatte optimiert man Retrieval nach Gefühl — und landet bei einem weiteren
System, das behauptet, besser zu sein.
