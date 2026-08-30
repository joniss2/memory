# provenance

**Gedächtnis-Layer mit Herkunftsspur.** Ein Container. Eine Datenbank. Jede
Erinnerung erklärt sich selbst.

Die Umsetzung des Architekturentwurfs in [`docs/ARCHITEKTUR.md`](docs/ARCHITEKTUR.md).
Dessen zentrale These: **Herkunftsspur und Auditlog sind dasselbe Artefakt.**
Wer nachvollziehen kann, warum ein Agent einen Fakt erinnert hat, kann auch
beantworten, woher dieser Fakt stammt und was bei seiner Löschung mitgeht.

---

## Was drin ist

| Baustein | Zustand |
| --- | --- |
| Schema: 7 Tabellen + Löschbeleg, bitemporal, `pgvector` mit HNSW | fertig |
| Stufe 1 Extraktion, mit protokollierten Nicht-Extraktionen | fertig |
| Stufe 2 Konsolidierung, asymmetrische Schwellen in Code | fertig |
| Stufe 3 Retrieval, RRF über Vektor + Volltext + Graph | fertig |
| Stufe 4 Injection, mit protokollierten Budget-Ausfällen | fertig |
| Löschung mit Vorschau, transitiver Hülle und Beleg | fertig |
| Bitemporales Replay auf beiden Zeitachsen | fertig |
| HTTP-API, MCP-Server, CLI | fertig |
| Dashboard: Entwickler- und Auskunftsansicht | fertig |
| Eval-Suite: 20 Änderungsszenarien, 4 Kennzahlen | fertig |

Die Reihenfolge aus Abschnitt 11 des Entwurfs ist eingehalten: die Eval stand
vor der Optimierung des Retrievals.

---

## Schnellstart

### Ein Container, alles drin

```bash
docker build -t provenance .

export PROVENANCE_API_TOKEN=$(openssl rand -hex 24)
docker run --rm -p 8080:8080 -e PROVENANCE_API_TOKEN \
  -v provenance-data:/var/lib/postgresql/data provenance
echo "Token: $PROVENANCE_API_TOKEN"
```

Danach: <http://localhost:8080/ui/> für die Entwickleransicht,
<http://localhost:8080/docs> für die API. Das Token trägt man im Dashboard
oben rechts einmal ein.

**Der Dienst verweigert den Start, wenn er über Loopback hinaus lauscht und
kein Token gesetzt ist.** Er bietet Abruf, Auskunft und Löschung
personenbezogener Daten an; das ungeschützt ins Netz zu stellen soll eine
Entscheidung sein, keine Vorgabe. Für eine Wegwerf-Umgebung genügt
`-e PROVENANCE_ALLOW_UNAUTHENTICATED=true`.

Ohne weitere Konfiguration läuft alles ohne Netz -- mit dem deterministischen
Modellersatz und gehashten Einbettungen. Das ist zum Ausprobieren gedacht,
nicht zum Betrieb; siehe [Modellanbindung](#modellanbindung).

### Lokal, gegen ein vorhandenes Postgres

```bash
pip install -e ".[dev,mcp]"
createdb provenance && psql provenance -c 'CREATE EXTENSION vector'
export PROVENANCE_DATABASE_URL=postgresql://localhost/provenance
provenance migrate

provenance ingest -s jonas -c "Ich wohne in Köln."      --at 2026-01-10
provenance ingest -s jonas -c "Ich bin nach Leipzig gezogen." --at 2026-06-14
provenance recall -s jonas -q "Wo wohnt er?"
provenance facts  -s jonas --all
```

```
  #   Status       gilt seit    gilt bis     Inhalt
  1   superseded   2026-01-10   2026-06-14   Wohnt in Köln.
  2   active       2026-06-14   -            Wohnt in Leipzig.
```

Der alte Fakt ist nicht weg. Er gilt nur nicht mehr, mit Zeitstempel und
Begründung -- und ist damit weiterhin abrufbar:

```bash
provenance recall -s jonas -q "Wo wohnt er?" --as-of-valid 2026-03-01
#  -> Wohnt in Köln.     (was galt im März?)
provenance recall -s jonas -q "Wo wohnt er?" --as-of-transaction 2026-02-01
#  -> Wohnt in Köln.     (was wusste das System im Februar?)
```

---

## Die vier Stufen

Jede schreibt ihren Trace-Schritt, auch wenn sie nichts gefunden hat.

**Stufe 1 -- Extraktion.** Kandidatenfakten mit Gültigkeitszeitpunkt und
Konfidenz. Mitgeschrieben werden auch die **Nicht-Extraktionen**: Sätze, die
das Modell als faktenfrei eingestuft hat, mit Begründung. Wenn ein Agent
etwas „vergessen" hat, wurde es meist hier nie extrahiert -- gesucht wird
aber traditionell in Stufe 3. Die Entwickleransicht zeigt darum Stufe 1
voreingestellt geöffnet.

**Stufe 2 -- Konsolidierung.** `add`, `update`, `retract`, `noop` oder
`merge`, mit Begründung. Zwei Härtungen stehen **in Code, nicht im Prompt**:

1. *Ein Widerspruch ist eine eigene Entscheidung, keine stille
   Überschreibung.* Der abgelöste Fakt bekommt `superseded`, behält seinen
   Inhalt und bleibt mit Zeitstempel abrufbar.
2. *Rückzug verlangt mehr Konfidenz als Hinzufügen.* Die Schwelle wird
   **nach** dem Modellaufruf angewandt -- ein Modell, das zu gern vergisst,
   kann sie nicht umreden. Wird eine Entscheidung überstimmt, steht die
   ursprünglich vorgeschlagene in `lineage.proposed_op` und die Begründung
   im Trace.

Dazu eine dritte, die sich im Bau als nötig erwies: **ein Modell darf nur
über Fakten entscheiden, die ihm vorgelegt wurden.** Erfundene Fakt-IDs
werden verworfen und der Vorgang protokolliert.

**Stufe 3 -- Retrieval.** Reciprocal Rank Fusion über drei Quellen:

| Quelle | Mechanik | Stärke |
| --- | --- | --- |
| Vektor | Kosinus über `facts.embedding` (HNSW) | Paraphrasen |
| Volltext | Postgres `tsvector`, ODER-verknüpft | Eigennamen, Zahlen |
| Graph | rekursives CTE ab erkannten Entitäten | mehrstufige Bezüge |

Alle drei laufen in einer Transaktion -- ein Snapshot, kein Netzwerk-Hop. Der
Trace hält je Kandidat Quelle, Rang und Platzierung nach der Fusion fest.

**Stufe 4 -- Injection.** Der tatsächlich in den Prompt gestellte Text, plus
die Liste dessen, was am Token-Budget gescheitert ist. Ein Fakt, der korrekt
extrahiert, gespeichert und gefunden wurde und an Rang 9 aus dem Budget
fällt, ist für den Agenten genauso abwesend wie einer, den es nie gab.

---

## Löschung

```bash
provenance erase -s jonas --facts 1            # Vorschau
provenance erase -s jonas --facts 1 --confirm  # ausführen
```

Die Vorschau nennt vor der Ausführung jede betroffene Zeile -- einschließlich
der **transitiven Hülle über `lineage.parent_id`**: Fakt 2 („Wohnt in
Leipzig") wurde aus Fakt 1 („Wohnt in Köln") abgeleitet und geht mit.

Ausgeführt wird dann:

1. `facts.status = 'erased'`; `content`, `embedding`, `content_tsv` und
   `triple` werden geleert, die Zeile bleibt
2. `edges.valid_to` gesetzt, wo `fact_id` betroffen ist
3. `trace_steps.input`/`output` **schemakonform geschwärzt** -- Schlüssel,
   Verschachtelung, Zeitstempel und Dauer bleiben, alle Blätter werden `null`
4. `turns.content` geleert, `redacted_at` gesetzt
5. `lineage.rationale` geleert -- eine Begründung wie „Aussage kehrt die
   Polarität zu ‚Espresso' um" zitiert den Wert, der verschwinden soll. Die
   Zeile mit `op` und `parent_id` bleibt: sie ist die Herkunftsspur.
6. `traces.query` geleert -- der Wortlaut einer Abfrage nennt oft genau den
   gesuchten Namen
7. Graphknoten, die kein nicht gelöschter Fakt mehr belegt, verlieren ihren Namen
8. Löschbeleg geschrieben

Die leere Zeile bleibt bewusst stehen: sie belegt, dass gelöscht wurde. Ein
spurloses `DELETE` kann man einer Aufsichtsbehörde nicht vorzeigen.

Nach der Löschung ist der Wert in **keiner** Tabelle mehr auffindbar. Genau
das prüft die Kennzahl `Erasure Completeness`, durch eine Volltextsuche über
alle sechs Ablagen, in denen ein Wert im Klartext stehen kann:
`facts.content`, `turns.content`, `entities.name`, `lineage.rationale`,
`traces.query` und `trace_steps`.

Die Liste in `RESIDUE_CHECKS` ist der eigentliche Inhalt dieser Zusage: was
dort fehlt, kann die Kennzahl nicht sehen. Die letzten drei Einträge kamen
erst nach einem Review dazu -- bis dahin meldete die Kennzahl 1,000, während
Begründung und Abfrage den gelöschten Wert noch trugen.

---

## Die Eval

```bash
provenance eval                      # 20 Szenarien, 4 Kennzahlen
provenance eval --only widerruf      # Teilmenge
provenance eval --out bericht.json
```

20 skriptgeführte Sitzungen über die fünf Muster des Entwurfs -- Ersetzung,
Verfeinerung, Befristung, Scheinwiderspruch, Widerruf -- mit Prüffragen an
definierten Kontrollpunkten. Gemessen wird gegen den Text aus **Stufe 4**,
nicht gegen die Trefferliste aus Stufe 3.

### Hat die Eval Zähne?

Eine Eval, die nur das eigene Vorgehen bewertet, könnte auch schlicht zu
leicht sein. Deshalb liegt ein Vergleichsmaßstab bei: `PROVENANCE_LLM_PROVIDER=naive`
konsolidiert so, wie es der übliche Zugriff tut -- ähnlichsten Fakt suchen,
über einer Schwelle überschreiben. Keine Prädikatslogik, keine Polarität,
kein Begriff von Widerruf.

| Kennzahl | strenge Konsolidierung | naiver Vergleichsmaßstab |
| --- | ---: | ---: |
| Update Recall | 1,000 | 1,000 |
| **Stale Rate** | **0,000** | **0,429** |
| False Retraction | 0,000 | 0,000 |
| Erasure Completeness | 1,000 | 1,000 |

Das ist die Positionierung aus Abschnitt 9 in Zahlen: **auf der Kennzahl, die
gängige Benchmarks ausweisen, sind die beiden nicht zu unterscheiden.** Der
Unterschied steckt in der Stale Rate -- und die weist heute niemand aus.

### Was die Zahlen nicht sagen

Die Suite meldet ausdrücklich, wenn eine Probe nichts belegen kann:

* **„ohne Grundlage"** -- der geprüfte Wert war nie gespeichert. Eine
  Stale-Probe auf einen nie extrahierten Wert besteht aus dem falschen Grund;
  sie zählt nicht in den Nenner. Ohne diese Regel sähe ein System, das gar
  nichts extrahiert, ausgerechnet in der Kennzahl gut aus, die es entlarven
  soll.
* **„Vorbedingung fehlt"** -- der widersprüchliche Satz eines
  Scheinwiderspruch-Szenarios wurde in Stufe 1 nie zu einem Fakt, die
  Konsolidierung also nie beansprucht. Im Lauf mit dem Modellersatz trifft
  das drei der vier Scheinwiderspruch-Szenarien. Das ist eine
  Extraktionslücke des Ersatzes, keine Konsolidierungsstärke -- und muss im
  Bericht stehen, sonst liest man das eine als das andere.

---

## Modellanbindung

Die einzige externe Abhängigkeit -- und mit Ollama oder vLLM lokal auflösbar.

```bash
export PROVENANCE_LLM_PROVIDER=openai
export PROVENANCE_LLM_BASE_URL=http://localhost:11434/v1   # Ollama
export PROVENANCE_LLM_MODEL_EXTRACT=qwen2.5:7b-instruct
export PROVENANCE_LLM_MODEL_CONSOLIDATE=qwen2.5:14b-instruct
export PROVENANCE_EMBEDDING_PROVIDER=openai
export PROVENANCE_EMBEDDING_MODEL=bge-m3
```

`openai` spricht jede OpenAI-kompatible Schnittstelle an: OpenAI selbst,
Ollama unter `/v1`, vLLM. Beide Stufen teilen sich einen Endpunkt, können aber
verschiedene Modelle benutzen -- die Kostenmaßnahme aus Abschnitt 10 (kleines
Modell für Stufe 1) ist damit erreichbar, solange derselbe Server beide
ausliefert.

> **Zu `heuristic`.** Die Vorgabe ist ein deterministischer Ersatz aus einer
> kleinen Mustertabelle, damit Tests, Eval und ein `docker run` ohne Modell
> durchlaufen. Er erfüllt dieselben zwei Verträge wie ein Modell, aber er
> versteht keine Sprache. **Seine Eval-Zahlen sagen etwas über die Mechanik
> der Pipeline aus, nichts über Qualität.** Für eine Qualitätsaussage gegen
> ein echtes Modell messen.

---

## Schnittstellen

```
POST /v1/turns                    Beitrag aufnehmen, Stufen 1--2
GET  /v1/recall                   Abruf, Stufen 3--4  (+ as_of_* auf beiden Zeitachsen)
GET  /v1/traces/:id               vollständiger Trace
GET  /v1/subjects/:id/export      DSGVO-Auskunft
POST /v1/subjects/:id/erase       Löschung mit Vorschau (ohne confirm nur Vorschau)
```

Dazu für die Ansichten: `/v1/subjects`, `/v1/subjects/:id/facts`,
`/v1/subjects/:id/timeline`, `/v1/subjects/:id/graph`,
`/v1/facts/:id/history`, `/v1/traces`, `/v1/replay`, `/healthz`.

**MCP-Server** mit denselben Operationen als Werkzeuge:

```bash
provenance-mcp              # stdio
```

`remember`, `recall`, `explain_fact`, `get_trace`, `export_subject`, `erase`.
`explain_fact` ist bewusst dabei: ein Assistent, der begründen kann, *warum*
er etwas erinnert, ist der Punkt der Übung.

---

## Dashboard

**Entwickleransicht** (`/ui/`) -- Turn-Zeitleiste mit der Zustandsänderung je
Beitrag, Trace-Inspektor über alle vier Stufen mit sichtbarer Prompt-Version,
Graph mit Zeitschieber (Kantenklick zeigt den belegenden Fakt und den
Ursprungs-Turn), Replay gegen die aktuellen Prompts mit Diff.

**Auskunftsansicht** (`/ui/auskunft`) -- was über eine Person gespeichert ist,
mit Quelle und Zeitpunkt; der Verlauf einer Angabe als lesbare Kette; Löschen
mit Vorschau. Dieselben Tabellen, andere Sprache: keine Modell-Interna.

Ist `PROVENANCE_API_TOKEN` gesetzt, verlangt die API ein Bearer-Token; das
Dashboard nimmt es in einem Feld entgegen und legt es im `localStorage` ab,
statt es in die Seite zu schreiben. `/healthz` bleibt offen.

---

## Betrieb

```bash
provenance prune-traces --days 30   # Traces auf Metadaten reduzieren
provenance storage                  # Tabellengrößen
provenance reindex                  # nach Wechsel von PROVENANCE_FTS_CONFIG
```

Die gestufte Aufbewahrung aus Abschnitt 10: Trace-Schritte älter als die
Frist verlieren `input` und `output`, behalten Stufe, Modell, Prompt-Version,
Dauer und Tokenzahlen. **Die Abstammung bleibt unbefristet** -- sie ist die
Herkunftsspur, nicht der Debug-Puffer.

---

## Entwicklung

```bash
pip install -e ".[dev,mcp]"
createdb provenance_test
python -m pytest          # 90 Tests gegen ein echtes Postgres
ruff check src tests
```

Die Tests laufen gegen ein echtes Postgres mit `pgvector`. Ein Ersatz wäre
hier wertlos: bitemporale Fenster, rekursive CTEs, HNSW und die
schemakonforme Schwärzung sind genau das, was geprüft werden soll.

---

## Abweichungen vom Entwurf

Bewusst und begründet:

* **Achte Tabelle.** Der Entwurf nennt sieben; Abschnitt 7 Schritt 6 verlangt
  einen Löschbeleg, der irgendwo stehen muss. `erasure_receipts` ist diese
  Stelle.
* **Rohmaterial bei der Löschung.** Die Schrittfolge in Abschnitt 7 lässt
  `turns.content` aus. Eine Löschung, die den Ursprungstext stehen lässt,
  wäre keine -- `turns` wird geschwärzt und `redacted_at` gesetzt.
* **Graphknoten bei der Löschung.** `entities.name` trägt selbst
  Personenbezug. Ein Knoten bleibt genau so lange inhaltlich stehen, wie ihn
  noch ein nicht gelöschter Fakt belegt.
* **Gültigkeitszeit-Semantik.** Bei einer Frage nach der Gültigkeitszeit ohne
  Transaktionszeit zählt ein `superseded` Fakt mit -- er hat in seinem
  Fenster gegolten --, ein `retracted` nie. Sonst könnte das System auf „wo
  hat er im März gewohnt?" nur schweigen, sobald jemand umgezogen ist.
* **Ungerichtete Graphtraversierung.** Abschnitt 4.4 zeigt eine gerichtete
  Abfrage; für einen Abruf ist die Gegenrichtung genauso interessant.
* **Zusätzliche Spalten.** `facts.triple` (strukturierte Projektion, speist
  den Graphen und gibt Stufe 2 einen Prädikatsvergleich statt reiner
  Textähnlichkeit), `facts.content_tsv`, `facts.erased_at`,
  `turns.redacted_at`, `trace_steps.redacted_at`, `lineage.proposed_op`.

---

## Was noch fehlt

* Ein Vergleich gegen mem0, Zep oder LoCoMo. Der Entwurf argumentiert
  ausdrücklich gegen LoCoMo als Maßstab; ein Zahlenvergleich mit den
  Wettbewerbern steht trotzdem aus.
* Die Extraktions- und Konsolidierungs-Prompts sind erst in Version 1 und
  gegen kein echtes Modell iteriert. Nach Abschnitt 10 sind genau sie das
  Produkt -- die Eval steht bereit, die Arbeit daran beginnt jetzt.
* Getrennte Endpunkte je Stufe (derzeit ein Endpunkt, zwei Modellnamen).
* `merge` ist in Schema, Richtlinie und Anwendung umgesetzt, wird vom
  Modellersatz aber nie vorgeschlagen und ist darum nur durch Tests belegt.
