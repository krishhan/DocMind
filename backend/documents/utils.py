import os
import threading
import logging
import pypdf
import fitz
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

def split_text_recursively(text, max_chunk_size=1500, overlap=200, separator_idx=0):
    separators = ["\n\n", "\n", ". ", " ", ""]
    if separator_idx >= len(separators):
        # Fallback to direct character slicing
        chunks = []
        start = 0
        while start < len(text):
            end = start + max_chunk_size
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start += (max_chunk_size - overlap)
        return chunks

    sep = separators[separator_idx]
    
    if sep == "":
        splits = list(text)
    else:
        splits = text.split(sep)
    
    chunks = []
    current_chunk = []
    current_len = 0
    
    for split in splits:
        if len(split) > max_chunk_size:
            # Clear current chunk first
            if current_chunk:
                joined = sep.join(current_chunk)
                if joined.strip():
                    chunks.append(joined.strip())
                current_chunk = []
                current_len = 0
            # Recursively split the long block
            sub_chunks = split_text_recursively(split, max_chunk_size, overlap, separator_idx + 1)
            chunks.extend(sub_chunks)
            continue
        
        sep_len = len(sep) if current_chunk else 0
        if current_len + len(split) + sep_len <= max_chunk_size:
            current_chunk.append(split)
            current_len += len(split) + sep_len
        else:
            if current_chunk:
                joined = sep.join(current_chunk)
                if joined.strip():
                    chunks.append(joined.strip())
            
            # Start new chunk with overlap
            overlap_chunk = []
            overlap_len = 0
            for prev_split in reversed(current_chunk):
                prev_sep_len = len(sep) if overlap_chunk else 0
                if overlap_len + len(prev_split) + prev_sep_len <= overlap:
                    overlap_chunk.insert(0, prev_split)
                    overlap_len += len(prev_split) + prev_sep_len
                else:
                    break
            
            current_chunk = overlap_chunk
            current_len = overlap_len
            
            sep_len = len(sep) if current_chunk else 0
            current_chunk.append(split)
            current_len += len(split) + sep_len
            
    if current_chunk:
        joined = sep.join(current_chunk)
        if joined.strip():
            chunks.append(joined.strip())
            
    return chunks

def extract_and_chunk_pdf(file_path, chunk_size=1500, chunk_overlap=200):
    chunks = []
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
                
                # Run recursive splitting on the page text
                page_chunks = split_text_recursively(text, chunk_size, chunk_overlap)
                
                for idx, chunk_text in enumerate(page_chunks):
                    chunks.append({
                        'text': chunk_text,
                        'page': page_num,
                        'chunk_in_page_idx': idx
                    })
    finally:
        if doc_fitz is not None:
            try:
                doc_fitz.close()
            except Exception:
                pass
                
    return chunks

def process_document_pipeline(document_id):
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error(f"Document {document_id} does not exist in database.")
        return

    try:
        # Extract text and chunk
        chunks = extract_and_chunk_pdf(document.file.path)
        
        if not chunks:
            raise ValueError("No extractable text found in this PDF.")

        # Load model and get collection
        model = get_embedding_model()
        collection = get_chroma_collection()

        # Prepare lists for batch Chroma insertion
        ids = []
        embeddings = []
        metadatas = []
        documents_texts = []

        chunk_objs = []
        for idx, chunk in enumerate(chunks):
            vector_id = f"doc_{document_id}_chunk_{idx}"
            
            emb_res = model.encode(chunk['text'])
            embedding = emb_res.tolist() if hasattr(emb_res, 'tolist') else list(emb_res)
            
            ids.append(vector_id)
            embeddings.append(embedding)
            metadatas.append({
                "document_id": document_id,
                "page_number": chunk['page'],
                "owner_id": document.owner.id
            })
            documents_texts.append(chunk['text'])

            # Create django database chunk instances
            chunk_objs.append(
                DocumentChunk(
                    document=document,
                    chunk_text=chunk['text'],
                    chunk_index=idx,
                    page_number=chunk['page'],
                    vector_id=vector_id
                )
            )

        # Bulk write chunks to DB
        DocumentChunk.objects.bulk_create(chunk_objs)

        # Write to ChromaDB
        collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents_texts
        )

        # Complete
        document.status = 'ready'
        document.save()
        logger.info(f"Successfully processed Document ID {document_id}: {len(chunks)} chunks embedded.")

    except Exception as e:
        logger.exception(f"Error processing Document ID {document_id}")
        try:
            document.status = 'failed'
            document.error_message = str(e)
            document.save()
        except Exception as inner_e:
            logger.error(f"Failed to save document error status: {str(inner_e)}")
    finally:
        import gc
        gc.collect()

def run_document_processing(document_id):
    from django.db import close_old_connections
    
    def thread_target():
        try:
            close_old_connections()
            process_document_pipeline(document_id)
        except Exception as thread_err:
            logger.exception(f"Unhandled error in document processing thread: {str(thread_err)}")
        finally:
            close_old_connections()
            
    thread = threading.Thread(target=thread_target, name=f"DocProcess-{document_id}")
    thread.daemon = True
    thread.start()
