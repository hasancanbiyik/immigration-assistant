# Deployment Guide — HuggingFace Spaces

Step-by-step procedure for deploying this project as a public demo on HuggingFace Spaces (Docker SDK, free CPU tier).

The repo is already configured for this target — `README.md` has the HF Space frontmatter, `Dockerfile` is multi-stage and self-contained, `app/main.py` serves the SPA from the same origin, and the frontend handles cold-start UX. All you need to do is create the Space and push.

---

## 0. Prerequisites

1. **HuggingFace account** — free, https://huggingface.co/join
2. **A Gemini API key** — free tier (15 RPM, 1M TPM), https://aistudio.google.com/app/apikey
3. **Git installed locally** — you'll push from your machine to HF's git server
4. **This repo cleanly committed** — `git status` should be clean before you start, otherwise the HF build won't see your latest changes

If `git status` shows uncommitted work, commit or stash it now.

---

## 1. Create the Space

1. Go to https://huggingface.co/new-space
2. Fill in:
   - **Owner**: your HF username
   - **Space name**: `immigration-assistant` (or whatever — this becomes part of the URL)
   - **License**: MIT
   - **Select the Space SDK**: **Docker** → choose **Blank** as the template (the YAML frontmatter in your README will configure the rest)
   - **Space hardware**: **CPU basic** (free) — 2 vCPU, 16 GB RAM. Plenty for MiniLM.
   - **Public**
3. Click **Create Space**

You'll land on the Space page with a "Files" tab and a `README.md` already created from your repo's frontmatter (assuming you push next).

---

## 2. Add the HF Space as a git remote and push

In your local repo:

```bash
cd /path/to/immigration-assistant
git remote add hf https://huggingface.co/spaces/<YOUR_HF_USERNAME>/<SPACE_NAME>
git push hf main
```

(Replace `<YOUR_HF_USERNAME>` and `<SPACE_NAME>` with your actual values.)

You'll be prompted for HuggingFace credentials:
- **Username**: your HF username
- **Password**: a **User Access Token** with `write` scope, NOT your account password. Create one at https://huggingface.co/settings/tokens.

If your default branch is `master` instead of `main`, use `git push hf master:main`.

The push triggers an automatic Docker build. First build takes **5–10 minutes** (downloads `python:3.11-slim`, installs pip deps including PyTorch which is large, builds React frontend, etc.).

---

## 3. Set Space secrets and variables

While the build runs, configure environment variables:

1. On your Space page → **Settings** → **Variables and secrets**
2. Add **two** entries:

   | Type     | Name              | Value                                              |
   |----------|-------------------|----------------------------------------------------|
   | Secret   | `GEMINI_API_KEY`  | your Gemini key from prerequisites                 |
   | Variable | `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2`           |

   > **Important.** `GEMINI_API_KEY` MUST be a **secret** (not a variable) — secrets are not exposed in build logs or container introspection. `EMBEDDING_MODEL` can be a regular variable because the value isn't sensitive.

3. After adding secrets, click **Factory rebuild** to ensure the container restarts and picks them up. (Adding secrets after the first build does not automatically restart — Spaces docs are misleading on this.)

---

## 4. Watch the build

1. On your Space page → **Logs** tab → **Build logs**
2. Look for:
   - `✓ Successfully installed ...` (pip install completed)
   - `vite v8.0.8 building client environment for production...` (frontend build started)
   - `✓ built in ...` (frontend build done)
   - Build status changes to **Running** in the top bar

If the build fails, see [Troubleshooting](#troubleshooting) below.

3. Once Running, look at the **Container logs** (separate from Build logs):
   - `✅ RFE tracker database ready (SQLite)`
   - `Loading embedding model: sentence-transformers/all-MiniLM-L6-v2`
   - `✅ Loaded sentence-transformers/all-MiniLM-L6-v2`
   - `✅ ChromaDB initialized at ./data/chromadb (0 documents in collection)`
   - `✅ Gemini LLM ready (gemini-2.5-flash)` ← if your secret is set correctly
   - `Uvicorn running on http://0.0.0.0:8000`

   If you see `Loading embedding model: BAAI/bge-m3` instead of MiniLM, your `EMBEDDING_MODEL` variable didn't take — factory-rebuild and double-check the settings page.

---

## 5. Verify end-to-end

1. Visit your Space URL: `https://<USERNAME>-<SPACE_NAME>.hf.space` (also linked from the Space page)
2. You should see the **"Loading the embedding model"** overlay for a few seconds, then the app.
3. Check the health endpoint directly: `https://<USERNAME>-<SPACE_NAME>.hf.space/api/health`
   - `"ready": true`
   - `"embedding_model": "sentence-transformers/all-MiniLM-L6-v2"`
   - `"modules.gemini_llm": "active"` ← if Gemini key worked
4. Click **"✨ Try with sample document"** in the Q&A panel. You should see:
   - A "Demo Client" gets created
   - The sample I-797 uploads
   - Suggested questions appear
5. Ask "What is the receipt number?" — should return EAC2390012345 with citation to page 1.

If any step fails, jump to Troubleshooting.

---

## 6. Embed in your portfolio site

The Space is iframable. On your portfolio (`hasancanbiyik.com`), add:

```html
<iframe
  src="https://<USERNAME>-<SPACE_NAME>.hf.space"
  frameborder="0"
  width="100%"
  height="900"
  allow="clipboard-read; clipboard-write"
  style="border-radius: 12px; border: 1px solid #e5e7eb;"
></iframe>
```

For a project detail page, also link directly to the Space URL so recruiters who land there see the HuggingFace branding (which doubles as resume signal for AI Engineer roles).

---

## 7. Updates after first deploy

```bash
# Make changes locally, commit, push to HF:
git add .
git commit -m "your message"
git push hf main
```

HF auto-rebuilds on push. No need to touch the Space settings unless you're adding new secrets/variables.

To also keep GitHub in sync (recommended — GitHub is your authoritative repo, HF mirrors it):

```bash
git push origin main   # GitHub
git push hf main       # HuggingFace
```

Or set up a single command:

```bash
git config alias.deploy '!git push origin main && git push hf main'
git deploy
```

---

## 8. Cost ceiling

- **Free CPU tier (current setup)**: $0/month forever. Container sleeps after ~48h of inactivity; cold-start ~30–60s on next visit. 16 GB RAM, 2 vCPU.
- **HF Pro ($9/mo)**: keeps Spaces from sleeping, faster CPU. Worth it during active job-search if you're actively linking the demo to recruiters.
- **HF persistent storage ($5/mo for 20 GB)**: if you ever want uploaded docs to survive between sessions. Not needed for a demo; described here for completeness.

You can flip to Pro and back at any time — the Space URL doesn't change.

---

## Troubleshooting

### Build fails with "no space left on device"
HF's build cache can fill. On the Space page → Settings → **Factory rebuild** clears it. If that doesn't work, the Docker image is likely too large — verify `.dockerignore` excludes `node_modules`, `.venv`, `data/`, `tests/`, and that the multi-stage build only copies `frontend/dist` (not the source) to the final stage.

### Container starts but `/api/health` returns 502
The app didn't bind to the port HF expects. Two things to check:
1. `README.md` frontmatter has `app_port: 8000`
2. `Dockerfile` `CMD` uses `--host 0.0.0.0 --port 8000`

Both must match. Don't change one without the other.

### `/api/health` returns `"gemini_llm": "fallback"` instead of `"active"`
The `GEMINI_API_KEY` secret isn't reaching the container. Three checks:
1. Settings → Variables and secrets — it's listed as **Secret** (not Variable)
2. You clicked **Factory rebuild** after adding it
3. The container logs show no `"GEMINI_API_KEY not set"` warning — if they do, the secret name has a typo

### App loads but every Q&A query says "I cannot find any relevant information"
The embedder loaded but ChromaDB has no documents. This is expected on a fresh container. Click "Try with sample document" to seed it, OR upload your own document.

### Sample document load fails with 404
The sample file isn't being served. Check that `frontend/public/sample-i797-notice.txt` exists in your repo and the Docker build copied it. Run locally:
```bash
cd frontend && npm run build && ls dist/
```
You should see `sample-i797-notice.txt` in `dist/`. Vite copies everything from `public/` to `dist/` automatically — if it's missing, the file isn't where you think it is.

### Cold-start takes 2+ minutes
Almost certainly using BGE-M3 instead of MiniLM. Verify `EMBEDDING_MODEL` variable is set to `sentence-transformers/all-MiniLM-L6-v2` and factory-rebuild. Check container logs for which model loaded.

### Out-of-memory during embedder load
With MiniLM on free CPU (16 GB RAM), this shouldn't happen. If it does:
- You're on a smaller tier than expected — check Settings → Hardware
- Multiple model loads stacking up — reduce uvicorn workers (already 1, but verify)

### Git push to HF fails with "permission denied"
Your User Access Token doesn't have `write` scope. Regenerate at https://huggingface.co/settings/tokens with **Write** access enabled.

### Build hangs at "transformers" install
PyTorch is huge (~2 GB download). First-time installs can take 5+ minutes. Be patient. Subsequent builds are cached and fast.

---

## What's NOT included in this deploy

- **Persistent storage** — uploads, RFE cases, and ChromaDB embeddings reset on every container restart. This is intentional for an ephemeral demo. To add persistence: HF Pro persistent storage ($5/mo for 20 GB) writes mounted at `/data` survive restarts; update `VectorStoreService` and `rfe_db` to use `/data/chromadb` and `/data/rfe.db`.
- **Auto-loaded sample documents** — currently the demo starts empty until someone clicks "Try with sample." A future enhancement could pre-load the sample on container start via a lifespan hook, so the demo is never empty.
- **Rate limiting** — free CPU has no DoS protection. If your demo gets unexpectedly popular, add `slowapi` or move to Pro.

---

## Reference

- HuggingFace Spaces docs: https://huggingface.co/docs/hub/spaces
- Docker SDK reference: https://huggingface.co/docs/hub/spaces-sdks-docker
- Spaces config reference (the YAML in README): https://huggingface.co/docs/hub/spaces-config-reference
