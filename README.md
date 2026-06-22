# DocMind — AI Document Q&A App (RAG)

DocMind is a full-stack AI Document Q&A application built on a Retrieval-Augmented Generation (RAG) architecture. Users can upload PDF documents, which are extracted, chunked, and embedded locally. They can then ask natural-language questions and receive AI responses grounded strictly in the document content, alongside clear page-number citations.

## Tech Stack Overview
* **Backend:** Django + Django REST Framework
* **Auth:** JWT-based Authentication (`djangorestframework-simplejwt`)
* **Vector Store:** ChromaDB (persisted locally on disk)
* **Embeddings:** Local `sentence-transformers` (`all-MiniLM-L6-v2`) — runs completely free without external API keys.
* **LLM:** OpenRouter API (accessed via the OpenAI SDK wrapper)
* **Frontend:** Next.js (App Router, TypeScript, Tailwind CSS v4, Lucide React icons)
* **Database:** SQLite (local development default) / PostgreSQL support

---

## Project Structure
```
DocMind/
├── backend/                  # Django project directory
│   ├── accounts/             # JWT auth endpoints (SignUp, Login, Refresh, Profile)
│   ├── chat/                 # Conversations, messages logging & LLM RAG pipelines
│   ├── documents/            # PDF text extraction, local sentence-transformer embedding
│   ├── docmind/              # Project settings and primary routing
│   ├── requirements.txt      # Backend Python dependencies
│   └── .env.example          # Environment variables template
└── frontend/                 # Next.js app directory
    ├── src/
    │   ├── app/              # Routes (/login, /signup, /dashboard, /documents/[id])
    │   ├── context/          # Auth context with token refresh fetch wrapper
    └── package.json          # Node dependencies
```

---

## Quick Start Setup Instructions

### 1. Backend Setup
1. Navigate to the `backend/` directory:
   ```bash
   cd backend
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy the environment variables template and configure your keys:
   Rename `.env.example` to `.env` or edit the existing `.env` file and set your OpenRouter API Key:
   ```env
   SECRET_KEY=django-insecure-your-secret-key-here
   DEBUG=True
   ALLOWED_HOSTS=*
   
   # OpenRouter LLM Configurations
   OPENROUTER_API_KEY=your_openrouter_api_key_here
   OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free
   ```
5. Apply database migrations:
   ```bash
   python manage.py migrate
   ```
6. Launch the development server:
   ```bash
   python manage.py runserver
   ```
   The backend will be running at `http://127.0.0.1:8000/`.

---

### 2. Frontend Setup
1. Navigate to the `frontend/` directory:
   ```bash
   cd ../frontend
   ```
2. Install package dependencies:
   ```bash
   npm install
   ```
3. (Optional) Setup frontend `.env.local` to point to a custom backend port, otherwise it defaults to port `8000`:
   ```env
   NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000
   ```
4. Launch the local Next.js dev server:
   ```bash
   npm run dev
   ```
   The frontend UI will be running at `http://localhost:3000/`.

---

## How it Works (RAG Pipeline)
1. **Document Upload:** The backend checks the PDF structure and initializes a background processing thread to extract text page-by-page.
2. **Text Chunking:** Chunks are sliced into sizes of `1500` characters (~500 tokens) with an overlap of `200` characters, keeping page mappings intact.
3. **Embedding & Indexing:** Chunks are fed into `sentence-transformers` locally to generate 384-dimensional dense vectors and saved inside **ChromaDB** with parent document references.
4. **Retrieval Q&A:** When a user queries a document, the query text is embedded, the top-5 matching document chunks are retrieved from ChromaDB, a context-grounded system prompt is compiled, and the history is sent to OpenRouter to generate answers with inline source page references.
5. **Rate Limiting:** Users are restricted to a maximum of **20 questions per day** to control OpenRouter API cost burdens.

## Swapping LLM Providers or Models
Since OpenRouter runs on an OpenAI-compatible SDK base:
* To change the active LLM, simply modify the `OPENROUTER_MODEL` variable in your backend `.env` file (e.g. swap it to `google/gemini-flash-1.5` or `meta-llama/llama-3.3-70b-instruct`).
* You can also switch to direct OpenAI services by modifying the `base_url` parameter in `chat/views.py` from `https://openrouter.ai/api/v1` to `https://api.openai.com/v1`, updating the `api_key` environment variable and changing the model names.
