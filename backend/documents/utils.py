import os
import re
import logging
import pypdf
import fitz
import tiktoken
from django.conf import settings
from .models import Document, DocumentChunk

logger = logging.getLogger(__name__)

# Cache embedding model as singleton to avoid reloading on every request
_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading sentence-transformers model (all-MiniLM-L6-v2) locally...")
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Model loaded successfully.")
    return _embedding_model

# Cache Cross-Encoder model as singleton
_reranker_model = None

def get_reranker_model():
    global _reranker_model
    if _reranker_model is None:
        logger.info("Loading Cross-Encoder model (BAAI/bge-reranker-base) locally...")
        from sentence_transformers import CrossEncoder
        _reranker_model = CrossEncoder('BAAI/bge-reranker-base')
        logger.info("Cross-Encoder model loaded successfully.")
    return _reranker_model

# Cache OCR engine as singleton to avoid reloading on every page/request
_ocr_engine = None

def get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        logger.info("Loading RapidOCR engine locally...")
        _ocr_engine = RapidOCR()
        logger.info("RapidOCR loaded successfully.")
    return _ocr_engine

def get_chroma_client():
    import chromadb
    return chromadb.PersistentClient(path=settings.CHROMA_DB_DIR)

def get_chroma_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(name="docmind_chunks")

def get_token_count(text: str) -> int:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text, disallowed_special=()))
    except Exception:
        # Fallback approximation: 1 token ≈ 4 characters
        return len(text) // 4

def clean_and_check_noisy(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    # Exclude page footers or simple numbers (e.g. "1", "Page 2 of 24", "12")
    if re.match(r'^(page\s+\d+|\d+\s+of\s+\d+|\d+)$', cleaned.lower()):
        return True
    # Exclude chunks containing mostly punctuation/special symbols
    alnum_chars = [c for c in cleaned if c.isalnum()]
    if len(alnum_chars) < (len(cleaned) * 0.3):
        return True
    return False

def split_text_recursively_tokens(text, max_tokens=500, overlap_tokens=50, separator_idx=0):
    separators = ["\n\n", "\n", ". ", " ", ""]
    if separator_idx >= len(separators):
        # Fallback split by word list
        chunks = []
        words = text.split()
        current_chunk = []
        current_tokens = 0
        for word in words:
            word_tokens = get_token_count(word)
            if current_tokens + word_tokens <= max_tokens:
                current_chunk.append(word)
                current_tokens += word_tokens
            else:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                current_chunk = [word]
                current_tokens = word_tokens
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        return chunks

    sep = separators[separator_idx]
    splits = text.split(sep) if sep != "" else list(text)
    
    chunks = []
    current_chunk = []
    current_tokens = 0
    
    for split in splits:
        split_tokens = get_token_count(split)
        
        # If this split alone exceeds limit, recursively divide it
        if split_tokens > max_tokens:
            if current_chunk:
                chunks.append(sep.join(current_chunk))
                current_chunk = []
                current_tokens = 0
            sub_chunks = split_text_recursively_tokens(split, max_tokens, overlap_tokens, separator_idx + 1)
            chunks.extend(sub_chunks)
            continue
            
        sep_tokens = get_token_count(sep) if current_chunk else 0
        if current_tokens + split_tokens + sep_tokens <= max_tokens:
            current_chunk.append(split)
            current_tokens += split_tokens + sep_tokens
        else:
            if current_chunk:
                chunks.append(sep.join(current_chunk))
            
            # Start next chunk with the overlap tokens
            overlap_chunk = []
            overlap_toks = 0
            for prev_split in reversed(current_chunk):
                prev_sep_toks = get_token_count(sep) if overlap_chunk else 0
                prev_toks = get_token_count(prev_split)
                if overlap_toks + prev_toks + prev_sep_toks <= overlap_tokens:
                    overlap_chunk.insert(0, prev_split)
                    overlap_toks += prev_toks + prev_sep_toks
                else:
                    break
            
            current_chunk = overlap_chunk
            current_tokens = overlap_toks
            
            sep_tokens = get_token_count(sep) if current_chunk else 0
            current_chunk.append(split)
            current_tokens += split_tokens + sep_tokens
            
    if current_chunk:
        chunks.append(sep.join(current_chunk))
        
    return chunks

def extract_and_chunk_pdf(file_path, chunk_size=500, chunk_overlap=50):
    raw_chunks = []
    doc_fitz = None
    try:
        with open(file_path, 'rb') as f:
            reader = pypdf.PdfReader(f)
            
            for page_idx, page in enumerate(reader.pages):
                page_num = page_idx + 1
                try:
                    text = page.extract_text()
                except Exception as e:
                    logger.error(f"Failed to extract digital text from page {page_num}: {str(e)}")
                    text = ""
                
                if text:
                    text = text.strip()
                
                # If digital text extraction is empty, try OCR fallback
                if not text:
                    logger.info(f"Page {page_num} has no digital text. Falling back to OCR...")
                    try:
                        if doc_fitz is None:
                            doc_fitz = fitz.open(file_path)
                        page_fitz = doc_fitz[page_idx]
                        pix = page_fitz.get_pixmap()
                        png_bytes = pix.tobytes("png")
                        
                        engine = get_ocr_engine()
                        result, _ = engine(png_bytes)
                        if result:
                            text = "\n".join([block[1] for block in result])
                            text = text.strip()
                    except Exception as ocr_err:
                        logger.error(f"OCR fallback failed for page {page_num}: {str(ocr_err)}")

                if not text:
                    continue
                
                # Dynamic heading & section heuristic (first line that is short and capitalized/keyterm)
                heading = ""
                section = ""
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                for line in lines[:3]:
                    if len(line) < 100 and (line.isupper() or any(s in line.lower() for s in ['chapter', 'section', 'introduction', 'conclusion', 'summary'])):
                        heading = line
                        break
                
                # Split page text using token-aware recursive splitter
                page_chunks = split_text_recursively_tokens(text, chunk_size, chunk_overlap)
                
                for idx, chunk_text in enumerate(page_chunks):
                    if clean_and_check_noisy(chunk_text):
                        continue
                        
                    raw_chunks.append({
                        'text': chunk_text,
                        'page': page_num,
                        'heading': heading,
                        'section': section,
                        'token_count': get_token_count(chunk_text)
                    })
    finally:
        if doc_fitz is not None:
            try:
                doc_fitz.close()
            except Exception:
                pass
                
    # Merge extremely small chunks (< 50 tokens) with adjacent chunks on the same page
    merged_chunks = []
    temp_chunk = None
    
    for chunk in raw_chunks:
        if chunk['token_count'] < 50:
            if temp_chunk is None:
                temp_chunk = chunk
            else:
                if temp_chunk['page'] == chunk['page']:
                    temp_chunk['text'] = temp_chunk['text'] + "\n" + chunk['text']
                    temp_chunk['token_count'] = get_token_count(temp_chunk['text'])
                    if temp_chunk['token_count'] >= 50:
                        merged_chunks.append(temp_chunk)
                        temp_chunk = None
                else:
                    merged_chunks.append(temp_chunk)
                    temp_chunk = chunk
        else:
            if temp_chunk is not None:
                if temp_chunk['page'] == chunk['page']:
                    chunk['text'] = temp_chunk['text'] + "\n" + chunk['text']
                    chunk['token_count'] = get_token_count(chunk['text'])
                else:
                    merged_chunks.append(temp_chunk)
                temp_chunk = None
            merged_chunks.append(chunk)
            
    if temp_chunk is not None:
        merged_chunks.append(temp_chunk)
        
    return merged_chunks

def split_text_recursively(text, max_chunk_size=1500, overlap=200):
    max_tokens = max(1, max_chunk_size // 4)
    overlap_tokens = max(0, overlap // 4)
    return split_text_recursively_tokens(text, max_tokens, overlap_tokens)
