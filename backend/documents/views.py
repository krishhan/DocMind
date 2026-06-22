import os
import logging
from rest_framework import status, permissions, generics
from rest_framework.response import Response
from .models import Document
from .serializers import DocumentSerializer
from .utils import run_document_processing, get_chroma_collection

logger = logging.getLogger(__name__)

class DocumentListUploadView(generics.ListCreateAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Document.objects.filter(owner=self.request.user).order_by('-upload_date')

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded."}, status=status.HTTP_400_BAD_REQUEST)
        
        if not file_obj.name.lower().endswith('.pdf'):
            return Response({"error": "Only PDF files are supported."}, status=status.HTTP_400_BAD_REQUEST)
        
        if file_obj.size > 10 * 1024 * 1024:
            return Response({"error": "File size exceeds the 10MB limit."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.save()
        
        # Trigger local sentence embedding thread
        run_document_processing(document.id)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class DocumentDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Document.objects.filter(owner=self.request.user)

    def perform_destroy(self, instance):
        # Clean up ChromaDB vectors for this document
        try:
            collection = get_chroma_collection()
            # chroma where clause filters by document_id metadata field
            collection.delete(where={"document_id": instance.id})
            logger.info(f"Deleted vectors for Document ID {instance.id} from ChromaDB")
        except Exception as e:
            logger.error(f"Failed to delete ChromaDB vectors for document {instance.id}: {str(e)}")
        
        # Clean up local PDF file
        if instance.file:
            try:
                if os.path.exists(instance.file.path):
                    os.remove(instance.file.path)
                    logger.info(f"Deleted file {instance.file.path} from media storage")
            except Exception as e:
                logger.error(f"Failed to delete file {instance.file.name}: {str(e)}")
                
        instance.delete()
