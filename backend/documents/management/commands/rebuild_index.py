import os
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings
from documents.models import Document, DocumentChunk
from documents.utils import get_embedding_model, get_chroma_collection

class Command(BaseCommand):
    help = 'Rebuilds ChromaDB vector index from SQLite database chunks.'

    def handle(self, *args, **options):
        self.stdout.write("Deleting existing ChromaDB directory to clear corruption...")
        chroma_dir = settings.CHROMA_DB_DIR
        if os.path.exists(chroma_dir):
            try:
                shutil.rmtree(chroma_dir)
                self.stdout.write(self.style.SUCCESS("Deleted chroma_db folder successfully."))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Could not delete chroma_db folder: {e}"))
        
        self.stdout.write("Initializing fresh ChromaDB collection...")
        collection = get_chroma_collection()
        
        # Fetch all chunks
        chunks = DocumentChunk.objects.select_related('document').all()
        total = chunks.count()
        self.stdout.write(f"Found {total} chunks in SQLite to re-index.")
        
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No chunks found in database. Rebuild complete."))
            return

        self.stdout.write("Loading embedding model...")
        model = get_embedding_model()
        
        ids = []
        embeddings = []
        metadatas = []
        documents_texts = []
        
        for idx, chunk in enumerate(chunks):
            # Compute embedding
            emb_res = model.encode(chunk.chunk_text)
            embedding = emb_res.tolist() if hasattr(emb_res, 'tolist') else list(emb_res)
            
            ids.append(chunk.vector_id)
            embeddings.append(embedding)
            metadatas.append({
                "document_id": chunk.document.id,
                "page_number": chunk.page_number,
                "owner_id": chunk.document.owner.id
            })
            documents_texts.append(chunk.chunk_text)
            
            # Batch write every 100 chunks
            if len(ids) >= 100:
                collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    documents=documents_texts
                )
                self.stdout.write(f"Indexed {idx + 1}/{total} chunks...")
                ids = []
                embeddings = []
                metadatas = []
                documents_texts = []
                
        # Final batch
        if ids:
            collection.add(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents_texts
            )
            
        self.stdout.write(self.style.SUCCESS(f"Successfully rebuilt ChromaDB index with all {total} chunks!"))
