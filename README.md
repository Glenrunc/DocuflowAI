# DocuFlow AI

Centralise les documents administratifs (factures, contrats, documents médicaux, rapports,
pièces d'identité/certificats), extrait leurs champs clés avec **OCR + LLM local**, les range
par type, et répond à des questions en langage naturel **sur un document ou sur toute la
collection** (avec raisonnement affiché en direct).

Tout tourne en local : OCR via **docTR**, modèle de langage via **Ollama** — aucun appel à
une API externe, aucun secret dans les images Docker.

## Architecture

| Couche | Choix | Pourquoi |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLModel | docTR/Ollama sont en Python ; typage strict |
| OCR | docTR (GPU, repli CPU) | géométrie au mot → zones des champs |
| LLM | Ollama `qwen2.5` (3b sur 6 Go de VRAM, 7b si ça tient) | un seul modèle pour le pipeline, la QA et la boucle d'agent |
| Embeddings | Ollama `nomic-embed-text` (768d) | texte OCR découpé en chunks, stocké en table `chunk` |
| BDD | Postgres (JSONB) | métadonnées + champs/zones/texte OCR/embeddings |
| File d'attente | table `jobs` + 1 worker (`FOR UPDATE SKIP LOCKED`) | sérialise le GPU ; durable ; pas de Redis |
| Frontend | React + TS + Vite, variables CSS | design tokens ; pas de framework UI lourd |

Les **schémas de champs vivent à un seul endroit**, `shared/schemas.json`, consommé à la
fois par le backend (validation Pydantic) et par le frontend (import typé). Six types :
invoice, contract, medical, report, id, other.

### Pipeline de traitement (worker, GPU sérialisé)

```
queued → processing → OCR (docTR) → classification du type (Ollama) → extraction des champs (Ollama, JSON strict)
       → validation contre le schéma → backstops (corrections déterministes) → dérivation des zones (bbox)
       → normalisation des montants en EUR → détection de doublons → rangement sur disque
       → découpage + embeddings (nomic-embed-text) → done
```

Les zones (bounding boxes) sont **dérivées côté serveur** en faisant correspondre chaque
valeur extraite à la géométrie des mots docTR (rapidfuzz) — jamais devinées par le LLM. La
détection de doublons compare les champs *identifiants* du type (similarité floue
normalisée), pas les embeddings.

Deux garde-fous déterministes à connaître :

- **Backstop du total** : si le texte OCR contient une ligne de total explicite (`TOTAL`,
  `AMOUNT DUE`, …) et que le total extrait par le LLM la contredit (typiquement le montant
  CASH/CHANGE), c'est la ligne du document qui gagne, quelle que soit la confiance du LLM.
- **Normalisation des devises** : les champs monétaires (`invoice.total`, `invoice.taxes`,
  `contract.value`) sont réécrits en EUR à taux fixes embarqués. Un montant sans symbole
  est converti selon la devise dominante du texte OCR (reçus SROIE : le `RM` est sur les
  lignes de prix, pas dans le total extrait). Les taux (`%`) ne sont jamais convertis.

### QA — deux portées

- **Document unique** : le texte OCR du document actif + ses champs extraits sont injectés
  dans le LLM. L'extrait cité est relocalisé dans le texte OCR → `Found on line N: "…"`.
- **Collection entière (RAG agentique)** : une boucle d'agent de type ReAct sur le même
  modèle `qwen2.5`. Les documents sont découpés (~500 mots, recouvrement 50) et plongés en
  vecteurs à l'indexation (`nomic-embed-text`, stockés en JSON dans la table `chunk`).
  L'agent dispose de **4 outils** : `search` (recherche hybride : cosinus sur les
  embeddings + recherche plein texte Postgres, fusion par reciprocal rank fusion),
  `filter` (type/mot-clé), `detail` (texte et champs complets d'un document), `aggregate`
  (somme/moyenne/min/max calculés côté serveur, jamais par le modèle). Chaque étape est un
  JSON strict, plafonnée à 20 étapes, avec détection d'action répétée. Le raisonnement est
  streamé en direct (NDJSON). Passe à l'échelle au-delà de la limite (~200 docs) de
  l'injection de contexte.

Les PDF sont affichés via une **image de page rendue côté serveur** (le même raster que
celui passé à docTR), donc la surbrillance des zones s'aligne exactement — le visualiseur
PDF natif du navigateur n'est pas utilisé.

## Démarrage rapide (Docker)

Nécessite Docker + le **NVIDIA Container Toolkit** pour le GPU.

```bash
cp .env.example .env          # à ajuster si besoin ; aucun secret requis
docker compose up --build     # démarre db, ollama, backend, worker, frontend
docker compose exec ollama ollama pull qwen2.5:3b       # LLM (une fois ; ou qwen2.5:7b avec >6 Go de VRAM)
docker compose exec ollama ollama pull nomic-embed-text  # modèle d'embeddings RAG (une fois)
```

> Sur une machine avec GPU local, utiliser `docker compose -f docker-compose.local.yml up --build` —
> elle réutilise les modèles Ollama déjà téléchargés sur l'hôte (pas de re-pull).

- Frontend : http://localhost:5173
- API : http://localhost:8000  (santé : `/api/health`)

Déposer un document, suivre la barre latérale `queued → processing → done`, puis inspecter
les champs extraits, survoler un champ pour surligner sa zone, poser une question, ou ouvrir
l'onglet Résumé pour exporter le CSV.

### Repli CPU (sans GPU)

Mettre `OCR_DEVICE=cpu` dans `.env` et retirer les blocs GPU `deploy.resources` des services
`ollama` et `worker` dans `docker-compose.yml`. Tout fonctionne — OCR et inférence sont
juste plus lents.

## Développement local (sans Docker)

**Backend** (nécessite un Postgres et un Ollama en marche) :

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+psycopg://docuflow:docuflow@localhost:5432/docuflow"
export OLLAMA_HOST="http://localhost:11434"
export OCR_DEVICE=cuda            # ou cpu

uvicorn app.main:app --reload     # API sur :8000
python -m app.worker              # worker, terminal séparé
```

Télécharger les modèles une fois : `ollama pull qwen2.5:3b && ollama pull nomic-embed-text`.

**Frontend :**

```bash
cd frontend
npm install
npm run dev                       # Vite sur :5173, proxy /api → :8000
```

## Configuration

Tous les réglages viennent de variables d'environnement (voir `backend/app/config.py` /
`.env.example`) :

| Variable | Défaut | Notes |
|---|---|---|
| `DATABASE_URL` | Postgres local | `postgresql+psycopg://…` |
| `OLLAMA_HOST` | `http://localhost:11434` | |
| `OLLAMA_MODEL` | `qwen2.5:3b` (docker) / `qwen2.5:7b` (défaut config) | pipeline + QA + boucle d'agent |
| `OLLAMA_QA_MODEL` | `qwen2.5:7b` | réponse de repli quand l'agent atteint son plafond d'étapes |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | modèle d'embeddings du RAG |
| `OCR_DEVICE` | `cuda` | `cpu` = repli dégradé |
| `DUPLICATE_THRESHOLD` | `0.85` | seuil de similarité |

### Note matériel

Développé sur une **RTX 3060 Laptop (6 Go de VRAM)**. docTR (~1,5 Go) + `qwen2.5:3b`
cohabitent sans problème, et `nomic-embed-text` n'ajoute que ~270 Mo. La boucle d'agent
réutilise le modèle du pipeline, donc rien n'est évincé. Les modèles plus gros (7B+)
forcent des chargements/déchargements entre OCR et inférence sur 6 Go — à réserver aux
cartes mieux dotées (`OLLAMA_MODEL=qwen2.5:7b`).

## Tests

```bash
cd backend && source .venv/bin/activate
pytest
```

83 tests couvrent la validation de schéma, la dérivation des zones, la similarité de
doublons, l'export CSV, la construction des citations, les backstops (dont l'écrasement par
la ligne de total), la normalisation des devises (détection, conversion, devise déduite de
l'OCR) et la boucle d'agent (parsing des actions, outils, agrégats). Le test d'intégration
(`test_pipeline_integration.py`) exécute l'orchestration complète `process_document` sur
SQLite en mémoire avec OCR et Ollama remplacés par des doublures — la suite ne nécessite
donc **ni GPU ni Ollama**. Un passage bout en bout sur la vraie pile se fait manuellement
via `docker compose up` (voir Démarrage rapide).

## Arborescence

```
shared/schemas.json        # source unique de vérité pour les 6 types de documents
backend/app/               # app FastAPI, routes, pipeline (ocr/classify/parse/bbox/embed/agent), worker
backend/tests/             # suite pytest
frontend/src/              # UI React + TS (pilotée par le schéma)
docker-compose.yml         # pile portable : db + ollama + backend + worker + frontend
docker-compose.local.yml   # pile GPU locale (réutilise les modèles Ollama de l'hôte)
```
