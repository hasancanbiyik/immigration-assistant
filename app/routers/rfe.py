"""
RFE Tracker Router
==================
CRUD endpoints for RFE cases and per-case issue checklists.

All data is stored in SQLite (./data/app.db, shared with timeline_events).
Issues are always fetched through their parent case_id,
so there is no way checklist items can bleed across cases or clients.

Endpoints:
  GET    /api/rfe/cases                         — list all cases (sorted by urgency)
  POST   /api/rfe/cases                         — create a case
  GET    /api/rfe/cases/{case_id}               — get case + its issues
  PUT    /api/rfe/cases/{case_id}               — update case fields
  DELETE /api/rfe/cases/{case_id}               — delete case + cascade issues

  POST   /api/rfe/cases/{case_id}/issues        — add issue to case
  PUT    /api/rfe/cases/{case_id}/issues/{iid}  — update issue
  DELETE /api/rfe/cases/{case_id}/issues/{iid}  — delete issue

  POST   /api/rfe/cases/{case_id}/extract-issues?mode=quick — regex extraction (fast, no tokens)
  POST   /api/rfe/cases/{case_id}/extract-issues?mode=ai   — Gemini extraction (reads images/scans)
"""

import re
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Query
from pydantic import BaseModel

from app.services import rfe_db
from app.utils.document_parser import DocumentParser, is_supported_document

logger = logging.getLogger(__name__)
router = APIRouter()
_document_parser = DocumentParser()


# ─── Request/Response models ──────────────────────────────────────────

class CreateCaseRequest(BaseModel):
    client_name: str
    case_type: Optional[str] = None
    receipt_number: Optional[str] = None
    service_center: Optional[str] = None
    rfe_issue_date: Optional[str] = None       # ISO date: YYYY-MM-DD
    response_deadline: Optional[str] = None    # ISO date; auto-calculated if omitted
    notes: str = ""


class UpdateCaseRequest(BaseModel):
    client_name: Optional[str] = None
    case_type: Optional[str] = None
    receipt_number: Optional[str] = None
    service_center: Optional[str] = None
    rfe_issue_date: Optional[str] = None
    response_deadline: Optional[str] = None
    status: Optional[str] = None               # open | in_progress | responded | approved | denied
    notes: Optional[str] = None


class AddIssueRequest(BaseModel):
    title: str
    description: str = ""


class UpdateIssueRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None


# ─── Case endpoints ───────────────────────────────────────────────────

@router.get("/cases")
async def list_cases(client_name: Optional[str] = None):
    """List all RFE cases, sorted by deadline urgency. Optionally filter by client."""
    return rfe_db.list_cases(client_name)


@router.post("/cases", status_code=201)
async def create_case(body: CreateCaseRequest):
    """
    Create a new RFE case.
    If rfe_issue_date is provided but response_deadline is not,
    the deadline is auto-calculated as issue_date + 87 days.
    """
    return rfe_db.create_case(
        client_name=body.client_name,
        case_type=body.case_type,
        receipt_number=body.receipt_number,
        service_center=body.service_center,
        rfe_issue_date=body.rfe_issue_date,
        response_deadline=body.response_deadline,
        notes=body.notes,
    )


@router.get("/cases/{case_id}")
async def get_case(case_id: str):
    """Get a single case with its full issues checklist."""
    case = rfe_db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.put("/cases/{case_id}")
async def update_case(case_id: str, body: UpdateCaseRequest):
    """Update case fields (partial update — only send what changed)."""
    case = rfe_db.update_case(case_id, **body.model_dump(exclude_none=True))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(case_id: str):
    """Delete a case and all its issues (cascading delete)."""
    if not rfe_db.delete_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")


# ─── Issue endpoints ──────────────────────────────────────────────────

@router.post("/cases/{case_id}/issues", status_code=201)
async def add_issue(case_id: str, body: AddIssueRequest):
    """Add a checklist item to a specific case."""
    issue = rfe_db.add_issue(case_id, body.title, body.description)
    if not issue:
        raise HTTPException(status_code=404, detail="Case not found")
    return issue


@router.put("/cases/{case_id}/issues/{issue_id}")
async def update_issue(case_id: str, issue_id: str, body: UpdateIssueRequest):
    """Update an issue's title, description, or completion state."""
    updates = body.model_dump(exclude_none=True)
    # SQLite stores booleans as integers
    if "completed" in updates:
        updates["completed"] = 1 if updates["completed"] else 0
    issue = rfe_db.update_issue(issue_id, **updates)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.delete("/cases/{case_id}/issues/{issue_id}", status_code=204)
async def delete_issue(case_id: str, issue_id: str):
    """Remove a checklist item."""
    if not rfe_db.delete_issue(issue_id):
        raise HTTPException(status_code=404, detail="Issue not found")


# ─── PDF auto-extract ─────────────────────────────────────────────────

# Patterns that typically appear before specific RFE issue descriptions
_ISSUE_PATTERNS = [
    # "You must submit/provide/furnish evidence of ..."
    r"(?i)(?:you\s+must|please)\s+(?:submit|provide|furnish|include)\s+(?:evidence|documentation|proof|copies?)\s+(?:of|that|showing|establishing)\s+(.{15,180}?)(?=\.|;|\n|$)",
    # Numbered list items containing key legal terms
    r"(?i)(?:^|\n)\s*\d+[\.\)]\s+(.{15,180}?(?:evidence|documentation|records?|proof|letter|statement|certificate).{0,60})(?=\.|;|\n|$)",
    # "The officer finds/notes that ..." — often introduces each issue
    r"(?i)(?:the\s+)?(?:officer|uscis)\s+(?:notes?|finds?|determines?|observes?)\s+that\s+(.{15,150}?)(?=\.|;|\n|$)",
    # "Failure to provide ..." — USCIS standard language for issue summary
    r"(?i)failure\s+to\s+provide\s+(.{15,150}?)(?=\s+may|will|could|\.|;|\n|$)",
]


@router.post("/cases/{case_id}/extract-issues")
async def extract_issues_from_pdf(
    request: Request,
    case_id: str,
    file: UploadFile = File(...),
    mode: str = Query(default="quick", pattern="^(quick|ai)$"),
):
    """
    Upload an RFE notice and auto-extract issues into the case's checklist.

    mode=quick  — Regex-based, fast, no API tokens.
                  Best for clean, searchable PDFs.
    mode=ai     — Gemini-powered, reads scanned/image PDFs via vision.
                  Uses API tokens; degrades gracefully to regex if Gemini unavailable.
    """
    case = rfe_db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if not is_supported_document(file.filename):
        raise HTTPException(status_code=400, detail="Unsupported file type (use PDF, TXT, or DOCX)")

    file_bytes = await file.read()

    # Always parse text — needed by both modes (regex uses it directly;
    # AI mode uses it as a fallback for non-binary formats like TXT/DOCX)
    try:
        parsed = _document_parser.parse_document(file_bytes, file.filename)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse document: {e}")

    issues_added = []
    extraction_method = mode  # will be updated if we fall back

    # ── AI mode: Gemini vision extraction ────────────────────────────
    if mode == "ai":
        gemini = request.app.state.gemini
        if gemini.is_available:
            extracted_titles = await gemini.extract_rfe_issues(
                file_bytes=file_bytes,
                filename=file.filename,
                text_fallback=parsed.full_text,
            )
            seen: set[str] = set()
            for title in extracted_titles:
                key = title.lower()[:80]
                if key not in seen:
                    seen.add(key)
                    issue = rfe_db.add_issue(case_id, title[:200])
                    if issue:
                        issues_added.append(issue)
        else:
            # Gemini not configured — fall back to regex automatically
            extraction_method = "quick (Gemini unavailable, fell back to regex)"
            mode = "quick"  # fall through to regex block below

    # ── Quick mode: regex extraction ──────────────────────────────────
    if mode == "quick":
        text = parsed.full_text
        seen = set()
        for pattern in _ISSUE_PATTERNS:
            for match in re.finditer(pattern, text, re.MULTILINE):
                title = match.group(1).strip().rstrip(".,;")
                title_key = title.lower()[:80]
                if title_key in seen or not (15 < len(title) < 220):
                    continue
                seen.add(title_key)
                issue = rfe_db.add_issue(case_id, title[:200])
                if issue:
                    issues_added.append(issue)

    # ── Universal fallback: nothing found by either method ────────────
    if not issues_added:
        fallback_msg = (
            "No specific issues could be auto-extracted. "
            "Please review the RFE notice manually and add items below."
        )
        issue = rfe_db.add_issue(
            case_id,
            f"Review RFE notice: {file.filename}",
            fallback_msg,
        )
        if issue:
            issues_added.append(issue)

    return {
        "issues_extracted": len(issues_added),
        "issues": issues_added,
        "source_file": file.filename,
        "extraction_method": extraction_method,
        "note": "Extraction is approximate — review and edit issues as needed.",
    }
