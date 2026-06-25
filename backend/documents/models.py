from django.db import models
from django.contrib.auth.models import User

class Document(models.Model):
    STATUS_CHOICES = (
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
    )

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='documents', db_index=True)
    filename = models.CharField(max_length=255)
    upload_date = models.DateTimeField(auto_now_add=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='processing')
    file = models.FileField(upload_to='documents/')
    error_message = models.TextField(blank=True, null=True)
    processing_progress = models.IntegerField(default=0)

    def __str__(self):
        return self.filename

class DocumentChunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks', db_index=True)
    chunk_text = models.TextField()
    chunk_index = models.IntegerField(db_index=True)
    page_number = models.IntegerField(db_index=True)
    vector_id = models.CharField(max_length=100)
    heading = models.CharField(max_length=255, blank=True, null=True)
    section = models.CharField(max_length=255, blank=True, null=True)
    token_count = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.document.filename} - Chunk {self.chunk_index} (Page {self.page_number})"
