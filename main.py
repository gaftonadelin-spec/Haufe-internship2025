# main.py
import os
import json
import tempfile
import requests
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# PDF generator
PDF_AVAILABLE = True
try:
    from fpdf import FPDF
except Exception:
    PDF_AVAILABLE = False
    print("[WARN] fpdf not installed. PDF generation fallback to text.")

app = FastAPI(title="AI Code Reviewer Backend")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Serve Frontend ---
base_dir = os.path.dirname(__file__)
frontend_candidate = os.path.normpath(os.path.join(base_dir, "..", "Frontend hackaton"))

if os.path.isdir(frontend_candidate):
    app.mount("/static", StaticFiles(directory=frontend_candidate), name="static")

    @app.get("/")
    async def root():
        index_html = os.path.join(frontend_candidate, "Index.html")
        index_html_lower = os.path.join(frontend_candidate, "index.html")
        if os.path.exists(index_html):
            return FileResponse(index_html)
        elif os.path.exists(index_html_lower):
            return FileResponse(index_html_lower)
        else:
            return JSONResponse({"detail": "Frontend index.html not found."})

    print(f"[INFO] Serving frontend from: {frontend_candidate}")
else:
    print("[WARN] Frontend folder not found. Static files not mounted.")

# --- Request Model ---
class CodeRequest(BaseModel):
    code: str
    language: Optional[str] = "python"
    request_pdf: Optional[bool] = False

# --- Build prompt ---
def build_prompt(code: str, language: str) -> str:
    return f"""
You are a senior software engineer and code reviewer. Analyze the {language} code and return a JSON object ONLY:
- summary, issues, suggestions, automatic_fixes, effort_estimate, docs_updates, metadata.
CODE:
\"\"\"{code}\"\"\"
"""

# --- Call Ollama LLM server ---
def call_llm(prompt: str) -> str:
    try:
        # Ollama local server URL
        url = "http://127.0.0.1:11434/v1/generate"
        payload = {
            "model": "llama3-8b-instruct",
            "prompt": prompt,
            "max_tokens": 1024
        }
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        # Ollama response text may be in data['completion'] or similar
        return data.get("completion", "")
    except Exception as e:
        print("[WARN] LLM server call failed, using simulated analysis:", e)
        return simulate_analysis(prompt)

# --- Simulated analysis ---
def simulate_analysis(prompt: str) -> str:
    code = ""
    if '"""' in prompt:
        parts = prompt.split('"""')
        if len(parts) >= 2:
            code = parts[1]

    issues = []
    summary = "Simulated analysis (LLM not available)."
    suggestions = []
    auto_fixes = []

    lines = code.splitlines()
    for idx, line in enumerate(lines, start=1):
        if "/ 0" in line or "/0" in line.replace(" ", ""):
            issues.append({
                "line": idx,
                "severity": "high",
                "title": "ZeroDivisionError possible",
                "description": "Division by zero detected. This will raise an exception at runtime."
            })
            suggestions.append("Check for division by zero before performing division.")
            auto_fixes.append({
                "description": "Add check for zero denominator",
                "patch": "if b != 0:\n    result = a / b\nelse:\n    result = None  # handle error"
            })

    if not issues:
        summary += " No obvious runtime errors detected."

    simulated = {
        "summary": summary,
        "issues": issues,
        "suggestions": suggestions,
        "automatic_fixes": auto_fixes,
        "effort_estimate": "5-15 minutes",
        "docs_updates": ["Add README section describing usage."],
        "metadata": {"language": "python", "analysis_time": "simulated"}
    }
    return json.dumps(simulated)

# --- Format analysis ---
def format_analysis(analysis: dict) -> str:
    output = ""
    output += f"### ✅ Summary\n{analysis.get('summary','')}\n\n"
    if analysis.get("issues"):
        output += "### ❌ Issues Found\n"
        for i, issue in enumerate(analysis["issues"], 1):
            line = issue.get("line", "N/A")
            output += f"{i}. **{issue.get('title')}** (line {line}, severity {issue.get('severity')}): {issue.get('description')}\n"
        output += "\n"
    if analysis.get("suggestions"):
        output += "### 💡 Suggestions\n"
        for s in analysis["suggestions"]:
            output += f"- {s}\n"
        output += "\n"
    if analysis.get("automatic_fixes"):
        output += "### 🛠️ Automatic Fixes\n"
        for fix in analysis["automatic_fixes"]:
            output += f"**{fix.get('description')}**\n```python\n{fix.get('patch')}\n```\n"
        output += "\n"
    if analysis.get("effort_estimate"):
        output += f"### ⏱️ Estimated Effort\n{analysis['effort_estimate']}\n\n"
    if analysis.get("docs_updates"):
        output += "### 📄 Documentation Updates\n"
        for d in analysis["docs_updates"]:
            output += f"- {d}\n"
        output += "\n"
    return output

# --- Analyze endpoint ---
@app.post("/analyze")
async def analyze_code(req: CodeRequest):
    if not req.code.strip():
        raise HTTPException(400, "No code provided.")

    prompt = build_prompt(req.code, req.language)
    raw_response = call_llm(prompt)

    try:
        parsed = json.loads(raw_response)
        parsed.setdefault("metadata", {})
        parsed["metadata"].setdefault("language", req.language)
    except Exception:
        parsed = {"summary": raw_response, "issues": [], "suggestions": [], "automatic_fixes": [],
                  "effort_estimate": None, "docs_updates": [], "metadata": {"language": req.language}}

    formatted = format_analysis(parsed)

    if req.request_pdf:
        tmp_file = os.path.join(tempfile.gettempdir(), f"analysis_{os.getpid()}.pdf")
        if PDF_AVAILABLE:
            try:
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                pdf.multi_cell(0, 8, formatted)
                pdf.output(tmp_file)
                return FileResponse(tmp_file, media_type="application/pdf", filename="analysis.pdf")
            except Exception as e:
                print("[WARN] PDF generation failed:", e)
        txt_file = tmp_file.replace(".pdf", ".txt")
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(formatted)
        return FileResponse(txt_file, media_type="text/plain", filename="analysis.txt")

    return JSONResponse({"formatted_analysis": formatted, "raw": parsed})

# --- Healthcheck ---
@app.get("/health")
async def health():
    return {"status": "ok"}
