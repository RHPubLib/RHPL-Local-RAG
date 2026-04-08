# RHPL Local RAG — Staff Policy & Procedures AI Assistant

Resources from **Rochester Hills Public Library (RHPL)** for running a local AI assistant
that answers staff questions about library policies and procedures — entirely on library-owned
hardware, with no data leaving the building.

---

## What This Is

Rochester Hills Public Library built a local AI assistant that helps staff quickly find
answers to policy and HR questions without having to search through binders, shared drives,
or PDF folders. Staff type a question in plain English:

- *"How many sick days do I get?"*
- *"What's the process for requesting bereavement leave?"*
- *"Can I renew a patron's card over the phone?"*
- *"What's our policy on patron behavior in the building?"*

The assistant reads RHPL's official policy documents and answers directly from them — citing
the specific policy number and document name so staff can always verify the source.

**The model only answers from official documents.** It does not guess, invent, or draw on
outside knowledge. If the answer isn't in the knowledge base, it says so and directs staff
to the library director. This makes it a reliable first stop, not a replacement for judgment.

### Why local matters

Staff questions about HR, leave, pay, and conduct involve sensitive information. Running this
model locally means those conversations stay inside RHPL's network — they are never sent to
OpenAI, Google, or any other cloud service. The same is true for patron-facing policy
questions that involve circulation rules, fines, or card eligibility.

There are no per-query fees. The model runs on hardware RHPL already owns and operates as
part of its local AI infrastructure (shared with the Polaris SQL helper — see
[Polaris-LEAP-SQL-AI-Helper](https://github.com/RHPubLib/Polaris-LEAP-SQL-AI-Helper)).

---

## Hardware Requirements

This model runs on the same server as RHPL's other local AI tools. A GPU with at least
10 GB VRAM is sufficient for a policies-and-procedures RAG model — the queries are
conversational rather than computationally intensive.

| Model | Min VRAM | Notes |
|-------|----------|-------|
| Qwen3-7B | ~10 GB | Good quality for RAG/Q&A tasks |
| Qwen3-14B | ~16 GB | RHPL's current model — handles all tools |
| Any instruction-tuned model | varies | Llama 3, Mistral, etc. will also work |

Any NVIDIA (CUDA) or AMD (ROCm) GPU will work. This use case is less demanding than SQL
generation — a modest GPU is sufficient if it's dedicated to this workload.

---

## How It Works

### The document pipeline

```
Original policy documents          Docling Serve             Open WebUI
(PDF, Word, PowerPoint)    ──►    (PDF → Markdown)    ──►   Knowledge Base
```

1. **Source documents** — RHPL's policy and procedure documents live in an organized folder
   structure on the server, grouped by category (Personnel Policies, Public Service
   Policies, Staff Knowledge, etc.). Documents can be PDF, Word (`.docx`), PowerPoint, or
   Excel.

2. **Docling conversion** — [Docling Serve](https://github.com/DS4SD/docling) runs as a
   Docker container and converts each document to clean Markdown. It uses OCR (Tesseract)
   for scanned PDFs, accurate table detection, and preserves document structure. The
   converted Markdown files mirror the original folder hierarchy.

3. **Knowledge base upload** — A Python script wipes and re-uploads all converted Markdown
   files to an Open WebUI knowledge base named **"RHPL Policies & Procedures"**. Open WebUI
   chunks, embeds, and indexes the content for retrieval.

4. **Model configuration** — A custom model in Open WebUI (`rhpl-policies-and-procedures`)
   is attached to the knowledge base and given a system prompt that constrains it to answer
   only from retrieved documents and to cite policy numbers.

When a staff member asks a question, Open WebUI retrieves the most relevant document chunks
and passes them to the model along with the question. The model answers using only what was
retrieved.

### Smart vocabulary translation

The system prompt instructs the model to translate staff casual language into policy
vocabulary before searching. For example:

| Staff asks… | Model searches for… |
|-------------|---------------------|
| "time off when someone dies" | bereavement leave |
| "call in sick" | sick leave |
| "can I work from home" | telework |
| "got hurt at work" | workers compensation |
| "written up" | disciplinary action |

This means staff don't need to know the official HR term — they can ask naturally.

---

## Repository Layout

```
README.md                    This file
system-prompt.md             The model's system prompt — paste into Open WebUI
docling-batch-convert.py     Converts source documents to Markdown via Docling Serve
owui-reload-kb.py            Wipes and re-uploads the Open WebUI knowledge base
```

---

## Setting Up the Knowledge Base

### 1. Run the infrastructure

You need three services running:

- **Open WebUI** — the chat interface and knowledge base engine
- **An LLM** — served via vLLM, Ollama, or any OpenAI-compatible backend
- **Docling Serve** — for converting PDFs and Word docs to Markdown

See RHPL's [Polaris-LEAP-SQL-AI-Helper](https://github.com/RHPubLib/Polaris-LEAP-SQL-AI-Helper)
for a full infrastructure setup guide using Docker Compose on an AMD ROCm GPU. The same
stack supports both tools.

### 2. Organize your policy documents

Create a folder structure on your server that mirrors your document categories. For example:

```
/path/to/kb-sources/
  Personnel Policies/
    General/
    Benefits/
    Work Rules/
  Public Service Policies/
    Circulation Policies/
    Customer Service Policies/
  Staff Knowledge/
```

Any folder depth works — Docling and the upload script traverse subdirectories recursively.

### 3. Convert documents to Markdown

Update the `INPUT_DIRS` and `OUTPUT_BASE` paths in `docling-batch-convert.py` to match your
folder structure, then run it:

```bash
python3 docling-batch-convert.py
```

Conversion is resumable — already-converted files are skipped. Docling handles scanned PDFs,
tables, and multi-column layouts well. Review the output Markdown for any documents that
converted poorly (complex forms and scanned images with low resolution may need manual
cleanup).

### 4. Create the knowledge base in Open WebUI

1. In Open WebUI, go to **Workspace → Knowledge → Create**
2. Name it something like **"RHPL Policies & Procedures"**
3. Use the upload script (`owui-reload-kb.py`) to upload all converted Markdown files, or
   upload them manually via the UI

### 5. Configure the model

1. In Open WebUI, go to **Workspace → Models → Create**
2. Set the base model to your Qwen3 (or other) model
3. Set **Temperature** to `0.1` — low temperature gives consistent, factual answers and
   reduces the chance of the model embellishing beyond what the documents say
4. Attach the knowledge base you created
5. Paste the contents of `system-prompt.md` into the **System Prompt** field
6. Save the model

---

## System Prompt

The full system prompt is in [`system-prompt.md`](system-prompt.md). Key behaviors it
enforces:

- **Documents only** — the model answers exclusively from retrieved policy documents and
  explicitly states when an answer is not found
- **Source citations** — every answer cites the policy document name and number
  (e.g., *"Per CIRC-2 Loan and Renewal Policy…"*)
- **Policy vs. Guidelines** — the model distinguishes between a Policy (binding rule) and
  Guidelines (procedural guidance), which is how RHPL's documents are structured
- **Redirect when unknown** — if the answer isn't in the knowledge base, the model says
  so clearly and directs the staff member to the library director

Adapt the prompt to match your library's document naming conventions and structure.

---

## Using This at Your Library

This setup is entirely document-agnostic — any library (or any organization) can load their
own policy documents and use the same pipeline.

**To adapt for your library:**

- Replace RHPL's source documents with your own policies, procedures, handbooks, and
  staff guides
- Update the system prompt to reference your library's name and any document naming
  conventions you use (e.g., your policy numbering scheme)
- Adjust the temperature if needed — `0.1` works well for factual Q&A, but a slightly
  higher value (e.g., `0.3`) may give more natural-sounding answers if the responses feel
  too terse
- The knowledge base can include any staff-facing documents: HR policies, circulation rules,
  customer service scripts, board policies, emergency procedures, etc.

**Document quality matters.** The model can only answer as well as the documents it retrieves.
Policies that are clearly written, well-organized, and consistently named will produce better
answers than legacy documents with inconsistent formatting.

---

## Contributing

If you adapt this for your library and make improvements to the system prompt, pipeline
scripts, or document structure, pull requests are welcome. The goal is to make this replicable
for any library that wants to give staff faster, more consistent access to institutional
knowledge.

---

Rochester Hills Public Library — Rochester Hills, Michigan
[rhpl.org](https://rhpl.org)
