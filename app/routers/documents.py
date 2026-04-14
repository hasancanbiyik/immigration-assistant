"""
Document Q&A Router
===================
Handles supported document uploads, chunking, embedding, and RAG-based Q&A.
"""

from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException
from typing import Optional
import logging

from app.utils.document_parser import (
    DocumentParser,
    SUPPORTED_DOCUMENT_EXTENSIONS,
    is_supported_document,
)
from app.models.schemas import (
    DocumentUploadResponse,
    QuestionRequest,
    QuestionResponse,
    SourceChunk,
    DocumentMetadata,
    CaseType,
    DocumentType,
)

logger = logging.getLogger(__name__)
router = APIRouter()
document_parser = DocumentParser()


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    client_name: Optional[str] = Form(None),
    case_type: Optional[str] = Form(None),
):
    """
    Upload a supported document for processing and embedding.
    
    The document will be:
    1. Parsed and text extracted
    2. Split into overlapping chunks
    3. Immigration metadata auto-extracted (receipt numbers, dates, case type)
    4. Embedded and stored in the vector store
    """
    if not is_supported_document(file.filename):
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Supported file types: {supported}.",
        )

    # Read file bytes
    file_bytes = await file.read()
    if len(file_bytes) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(
            status_code=400,
            detail="File too large. Maximum size is 50MB.",
        )

    # Parse document
    try:
        parsed = document_parser.parse_document(file_bytes, file.filename)
    except Exception as e:
        logger.error(f"Failed to parse document: {e}")
        raise HTTPException(
            status_code=422,
            detail=f"Failed to parse document: {str(e)}",
        )

    # Determine case type and document type
    effective_case_type = case_type or parsed.metadata.detected_case_type
    doc_type = parsed.metadata.detected_document_type

    # Store chunks in vector store
    vector_store = request.app.state.vector_store
    chunks_added = vector_store.add_chunks(
        chunks=parsed.chunks,
        client_name=client_name,
        case_type=effective_case_type,
        document_type=doc_type,
    )

    metadata = DocumentMetadata(
        client_name=client_name,
        case_type=CaseType(effective_case_type) if effective_case_type else None,
        document_type=DocumentType(doc_type) if doc_type else None,
        filing_date=parsed.metadata.dates[0] if parsed.metadata.dates else None,
        receipt_number=(
            parsed.metadata.receipt_numbers[0]
            if parsed.metadata.receipt_numbers
            else None
        ),
        source_filename=file.filename,
        page_number=1,
        chunk_index=0,
    )

    return DocumentUploadResponse(
        document_id=parsed.document_id,
        filename=file.filename,
        pages_processed=parsed.total_pages,
        chunks_created=chunks_added,
        extracted_metadata=metadata,
        message=(
            f"Successfully processed {file.filename}: "
            f"{parsed.total_pages} pages, {chunks_added} chunks indexed. "
            f"Detected case type: {effective_case_type or 'unknown'}. "
            f"Receipt numbers found: {parsed.metadata.receipt_numbers or 'none'}."
        ),
    )


@router.post("/ask", response_model=QuestionResponse)
async def ask_question(request: Request, body: QuestionRequest):
    """
    Ask a question about uploaded immigration documents.
    
    Uses RAG: retrieves relevant chunks from the vector store,
    then sends them as context to the LLM for answer generation.
    """
    vector_store = request.app.state.vector_store

    # Retrieve relevant chunks
    results = vector_store.query(
        question=body.question,
        top_k=body.top_k,
        client_name=body.client_name,
        case_type=body.case_type.value if body.case_type else None,
    )

    if not results:
        return QuestionResponse(
            answer=(
                "I couldn't find any relevant information in the uploaded documents. "
                "Please make sure you've uploaded the relevant case files, or try "
                "rephrasing your question."
            ),
            sources=[],
            confidence=0.0,
        )

    # Build context from retrieved chunks
    context_parts = []
    sources = []
    for i, result in enumerate(results):
        context_parts.append(
            f"[Source {i+1} — {result['metadata'].get('source_filename', 'unknown')}, "
            f"Page {result['metadata'].get('page_number', '?')}]\n"
            f"{result['text']}"
        )
        sources.append(
            SourceChunk(
                text=result["text"][:500],  # Truncate for response
                score=result["score"],
                metadata=DocumentMetadata(
                    source_filename=result["metadata"].get("source_filename", ""),
                    page_number=result["metadata"].get("page_number", 0),
                    chunk_index=result["metadata"].get("chunk_index", 0),
                    client_name=result["metadata"].get("client_name"),
                    case_type=result["metadata"].get("case_type"),
                    document_type=result["metadata"].get("document_type"),
                ),
            )
        )

    context = "\n\n---\n\n".join(context_parts)

    # Generate answer with Gemini (or fallback)
    gemini = request.app.state.gemini
    llm_result = await gemini.generate_answer(
        question=body.question,
        retrieved_chunks=results,
        client_name=body.client_name,
        case_type=body.case_type.value if body.case_type else None,
    )

    return QuestionResponse(
        answer=llm_result["answer"],
        sources=sources,
        confidence=llm_result["confidence"],
    )


@router.get("/stats")
async def get_document_stats(request: Request):
    """Get statistics about uploaded documents."""
    vector_store = request.app.state.vector_store
    return vector_store.get_collection_stats()


@router.get("/client/{client_name}")
async def list_client_documents(request: Request, client_name: str):
    """List all documents stored under a specific client name."""
    vector_store = request.app.state.vector_store
    filenames = vector_store.list_documents_by_client(client_name)
    return {"client_name": client_name, "documents": filenames}


@router.delete("/client/{client_name}/{filename}")
async def delete_client_document(request: Request, client_name: str, filename: str):
    """Delete a specific document for a specific client."""
    vector_store = request.app.state.vector_store
    deleted = vector_store.delete_document(filename, client_name=client_name)
    if deleted == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No document '{filename}' found for client '{client_name}'",
        )
    return {
        "message": f"Deleted {deleted} chunks for '{filename}' (client: {client_name})",
        "filename": filename,
        "client_name": client_name,
        "chunks_deleted": deleted,
    }


@router.delete("/{filename}")
async def delete_document(request: Request, filename: str):
    """Delete a document and all its chunks from the vector store (all clients)."""
    vector_store = request.app.state.vector_store
    deleted = vector_store.delete_document(filename)
    if deleted == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No document found with filename: {filename}",
        )
    return {
        "message": f"Deleted {deleted} chunks for {filename}",
        "filename": filename,
        "chunks_deleted": deleted,
    }
