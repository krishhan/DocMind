from rest_framework import serializers
from .models import Document, DocumentChunk

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ('id', 'filename', 'upload_date', 'status', 'file', 'error_message', 'processing_progress')
        read_only_fields = ('id', 'filename', 'upload_date', 'status', 'error_message', 'processing_progress')

    def create(self, validated_data):
        file = validated_data['file']
        filename = file.name
        owner = self.context['request'].user
        
        document = Document.objects.create(
            owner=owner,
            filename=filename,
            file=file,
            status='processing'
        )
        return document
