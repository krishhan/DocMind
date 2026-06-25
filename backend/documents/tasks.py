import logging
from celery import shared_task
from django.db import transaction
from .models import Document, DocumentChunk
from .utils import extract_and_chunk_pdf, get_embedding_model, get_chroma_collection

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_document_task(self, document_id):
    logger.info(f"Starting Celery document processing task for Document ID: {document_id}", extra={"document_id": document_id})
    try:
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            logger.error(f"Document {document_id} not found in database.", extra={"document_id": document_id})
            return

        # 1. Update progress -> 10%
        document.status = 'processing'
        document.processing_progress = 10
        document.error_message = None
        document.save()

        # 2. Extract and chunk PDF
        logger.info(f"Extracting and chunking document {document_id} from {document.file.path}", extra={"document_id": document_id})
        chunks = extract_and_chunk_pdf(document.file.path)
        
        if not chunks:
            raise ValueError("No extractable text found in this PDF.")

        document.processing_progress = 30
        document.save()

        # 3. Load embedding model and Chroma Collection
        model = get_embedding_model()
        collection = get_chroma_collection()

        document.processing_progress = 50
        document.save()

        # 4. Compute embeddings & build lists
        ids = []
        embeddings = []
        metadatas = []
        documents_texts = []
        chunk_objs = []
        
        total_chunks = len(chunks)
        logger.info(f"Computing embeddings for {total_chunks} chunks of Document ID {document_id}", extra={"document_id": document_id})
        
        for idx, chunk in enumerate(chunks):
            vector_id = f"doc_{document_id}_chunk_{idx}"
            
            # Encode chunk text
            emb_res = model.encode(chunk['text'])
            embedding = emb_res.tolist() if hasattr(emb_res, 'tolist') else list(emb_res)
            
            ids.append(vector_id)
            embeddings.append(embedding)
            
            # Store metadata
            metadata = {
                "document_id": document_id,
                "page_number": chunk['page'],
                "owner_id": document.owner.id,
                "heading": chunk.get('heading', ''),
                "section": chunk.get('section', ''),
                "token_count": chunk.get('token_count', 0),
                "chunk_index": idx
            }
            metadatas.append(metadata)
            documents_texts.append(chunk['text'])

            chunk_objs.append(
                DocumentChunk(
                    document=document,
                    chunk_text=chunk['text'],
                    chunk_index=idx,
                    page_number=chunk['page'],
                    vector_id=vector_id,
                    heading=chunk.get('heading', ''),
                    section=chunk.get('section', ''),
                    token_count=chunk.get('token_count', 0)
                )
            )
            
            # Update progress dynamically during embedding
            if idx % max(1, total_chunks // 5) == 0 or idx == total_chunks - 1:
                progress = 50 + int((idx + 1) / total_chunks * 40)
                document.processing_progress = min(90, progress)
                document.save()

        # 5. Insert DB records and Chroma vectors
        with transaction.atomic():
            # Clear existing chunks in case of retry
            DocumentChunk.objects.filter(document=document).delete()
            DocumentChunk.objects.bulk_create(chunk_objs)

        logger.info(f"Adding {len(ids)} vectors to ChromaDB for Document ID {document_id}", extra={"document_id": document_id})
        
        # Clear existing vectors in ChromaDB for this document in case of retry
        try:
            collection.delete(where={"document_id": document_id})
        except Exception:
            pass
            
        collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents_texts
        )

        # 6. Complete status -> 100%
        document.status = 'ready'
        document.processing_progress = 100
        document.save()
        logger.info(f"Successfully processed Document ID {document_id}", extra={"document_id": document_id})

    except Exception as e:
        logger.exception(f"Error processing Document ID {document_id}", extra={"document_id": document_id})
        try:
            doc_to_update = Document.objects.get(id=document_id)
            if self.request.retries < self.max_retries:
                doc_to_update.status = 'processing'
                doc_to_update.error_message = f"Processing failed, retrying... (Attempt {self.request.retries + 1}/{self.max_retries})"
                doc_to_update.save()
                raise self.retry(exc=e)
            else:
                doc_to_update.status = 'failed'
                doc_to_update.error_message = str(e)
                doc_to_update.processing_progress = 0
                doc_to_update.save()
        except Exception as retry_err:
            logger.error(f"Failed to save document error status for {document_id}: {str(retry_err)}", extra={"document_id": document_id})
            raise e
