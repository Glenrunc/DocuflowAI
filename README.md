# DocuFlow AI

Centralise des documents administratifs (factures, contrats, formulaires médicaux,
rapports, pièces d'identité/certificats), extrait leurs champs clés avec **OCR + un LLM
local**, les organise par type et répond à des questions en langage naturel **sur un seul
document ou sur l'ensemble de la collection** (avec « réflexion » en direct).

Tout s'exécute localement : OCR via **docTR**, modèle de langage via **Ollama** — aucun
appel API externe, aucun secret inscrit dans les images.

## Architecture

| Couche | Choix | Pourquoi |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLModel | docTR/Ollama sont en Python ; typage strict |
| OCR | docTR (GPU, repli CPU) | imposé ; géométrie au niveau du mot → bboxes des champs |
| LLM | Ollama `qwen2.5:3b` (pipeline) + `qwen3:4b` (réflexion QA) | local ; tient dans 6 Go de VRAM avec docTR |
| BD | Postgres (JSONB) | métadonnées + champs extraits/bboxes/texte OCR |
| File d'attente | table `jobs` + 1 worker (`FOR UPDATE SKIP LOCKED`) | sérialise le GPU ; durable ; sans Redis |
| Frontend | React + TS + Vite, variables CSS | tokens de design ; pas de framework UI lourd |

Les **schémas de champs vivent une seule fois** dans `shared/schemas.json`, consommés à la
fois par le backend (validation Pydantic) et le frontend (import typé). Six types : facture,
contrat, médical, rapport, identité, autre.

### Pipeline de traitement (worker, GPU sérialisé)

```
queued → processing → OCR (docTR) → classification du type (Ollama) → extraction des champs (Ollama, JSON strict)
       → validation contre le schéma → dérivation des bbox (correspondance valeur ↔ mots docTR) → détection de doublons → done
```

Les boîtes englobantes sont **dérivées côté serveur** en faisant correspondre chaque valeur
extraite avec la géométrie des mots docTR (rapidfuzz) — jamais devinées par le LLM. La
détection de doublons compare les champs *identifiants* du type (similarité floue
normalisée), pas des embeddings.

### QA — deux portées (sans vector store, sans embeddings)

- **Document unique** : le texte OCR du document actif + ses champs extraits sont injectés
  dans `qwen2.5:3b`. L'extrait cité est relocalisé dans le texte OCR → `Found on line N: "…"`.
- **Collection entière** : un **résumé structuré** compact (champs clés par document +
  agrégats, réutilisant l'agrégation du Résumé) est fourni à `qwen3:4b`, qui **diffuse sa
  réflexion en direct** (NDJSON, borné dans le temps) avant la réponse. Pas d'injection
  d'OCR brut, donc ça passe à l'échelle sur de nombreux documents.

Les PDF sont affichés comme **image de page rendue côté serveur** (le même raster docTR),
afin que la superposition des boîtes englobantes de champs s'aligne exactement — le visualiseur
PDF natif du navigateur n'est pas utilisé.

## Démarrage rapide (Docker)

Nécessite Docker + le **NVIDIA Container Toolkit** pour le GPU.

```bash
cp .env.example .env          # ajuster si besoin ; aucun secret requis
docker compose up --build     # démarre db, ollama, backend, worker, frontend
docker compose exec ollama ollama pull qwen2.5:3b   # modèle pipeline (une fois)
docker compose exec ollama ollama pull qwen3:4b     # modèle de réflexion QA collection (une fois)
```

> Sur une machine GPU locale, utiliser `docker compose -f docker-compose.local.yml up --build` —
> il monte (bind-mount) les modèles Ollama déjà téléchargés de l'hôte (pas de re-téléchargement).

- Frontend : http://localhost:5173
- API : http://localhost:8000  (santé : `/api/health`)

Téléversez un document, regardez la barre latérale passer `queued → processing → done`, puis
inspectez les champs extraits, survolez un champ pour mettre en évidence sa bbox, posez une
question, ou ouvrez l'onglet Résumé pour exporter en CSV.

### Repli CPU (sans GPU)

Définir `OCR_DEVICE=cpu` dans `.env` et retirer les blocs GPU `deploy.resources` pour les
services `ollama` et `worker` dans `docker-compose.yml`. Tout fonctionne toujours — l'OCR et
l'inférence sont juste plus lents.

## Développement local (sans Docker)

**Backend** (nécessite un Postgres + Ollama en cours d'exécution) :

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

Télécharger les modèles une fois : `ollama pull qwen2.5:3b && ollama pull qwen3:4b`.

**Frontend :**

```bash
cd frontend
npm install
npm run dev                       # Vite sur :5173, proxie /api → :8000
```

## Configuration

Tous les paramètres proviennent de variables d'environnement (voir `backend/app/config.py` /
`.env.example`) :

| Variable | Défaut | Notes |
|---|---|---|
| `DATABASE_URL` | Postgres local | `postgresql+psycopg://…` |
| `OLLAMA_HOST` | `http://localhost:11434` | |
| `OLLAMA_MODEL` | `qwen2.5:3b` | pipeline (classification/extraction) + QA document unique |
| `OLLAMA_QA_MODEL` | `qwen3:4b` | QA collection ; modèle de raisonnement/réflexion |
| `OCR_DEVICE` | `cuda` | `cpu` = repli dégradé |
| `DUPLICATE_THRESHOLD` | `0.85` | seuil de similarité |

### Note matérielle

Développé sur un **RTX 3060 Laptop (6 Go VRAM)**. docTR (~1,5 Go) + `qwen2.5:3b` (pipeline)
coexistent confortablement ; le modèle QA `qwen3:4b` est chargé à la demande (`keep_alive`)
et peut brièvement évincer le modèle pipeline — acceptable puisque la QA collection est
interactive. Des modèles plus gros (8B) forceraient des chargements/déchargements constants
et ne sont pas le choix par défaut.

## Tests

```bash
cd backend && source .venv/bin/activate
pytest
```

Les tests unitaires couvrent la validation des schémas, la dérivation des bbox, la similarité
de doublons, l'export CSV et la construction des citations. Le test d'intégration
(`test_pipeline_integration.py`) exécute toute l'orchestration `process_document` sur SQLite
en mémoire avec l'OCR et Ollama simulés (mock) — la suite n'a donc **besoin ni de GPU ni
d'Ollama**. Un run end-to-end sur la vraie stack est exercé manuellement via
`docker compose up` (voir Démarrage rapide).

## Structure

```
shared/schemas.json        # source unique de vérité pour les 6 types de documents
backend/app/               # app FastAPI, routes, pipeline (ocr/classify/parse/bbox/dup), worker
backend/tests/             # suite pytest
frontend/src/              # UI React + TS (pilotée par les schémas)
docker-compose.yml         # stack portable : db + ollama + backend + worker + frontend
docker-compose.local.yml   # stack GPU local (réutilise les modèles Ollama de l'hôte)
```
