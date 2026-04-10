# Research Agent

`Research Agent` is a lightweight research assistant project for AI Agent interview prep. It uses a small public-paper demo corpus and can be extended to OpenAlex, arXiv, or QASPER exports without changing the core code.

## What It Does

- Searches a local paper corpus with TF-IDF retrieval
- Answers research questions with evidence citations
- Compares multiple papers on methods, findings, and limitations
- Produces short topic reviews and reading plans
- Runs an offline evaluation suite
- Exposes both a CLI and a local browser UI
- Uses Alibaba Cloud DashScope Qwen when `DASHSCOPE_API_KEY` is configured
- Falls back to local rule-based synthesis when no model key is available

## DashScope Setup

Set the key as an environment variable instead of hardcoding it into the repo.

```powershell
$env:DASHSCOPE_API_KEY = 'your-key'
$env:DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
$env:DASHSCOPE_MODEL = 'qwen-plus'
```

## Run

```powershell
& "C:\ProgramData\anaconda3\python.exe" -m research_agent.cli ask --question "How does ReAct combine reasoning with tool use?"
& "C:\ProgramData\anaconda3\python.exe" -m research_agent.server
```

Then open `http://127.0.0.1:8000` in your browser.

## Project Layout

```text
research-agent/
  data/
    demo_papers.json
    demo_eval.json
  frontend/
    app.js
    index.html
    styles.css
  research_agent/
    agent.py
    cli.py
    corpus.py
    evaluation.py
    llm.py
    models.py
    retrieval.py
    server.py
  scripts/
    prepare_openalex.py
    prepare_qasper.py
  tests/
    test_agent.py
```

## Public Data Extension

1. Download OpenAlex works JSONL or arXiv metadata exports.
2. Run `scripts/prepare_openalex.py` to convert them into the local corpus format.
3. Download QASPER locally and run `scripts/prepare_qasper.py` to create an eval split.
4. Replace TF-IDF retrieval with hybrid retrieval or reranking when you are ready.
