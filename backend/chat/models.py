from django.db import models
from django.contrib.auth.models import User
from documents.models import Document

class Conversation(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='conversations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    created_at = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=255, default="New Conversation")

    def __str__(self):
        return f"Chat for {self.document.filename} by {self.user.username}"

class Message(models.Model):
    ROLE_CHOICES = (
        ('user', 'User'),
        ('assistant', 'Assistant'),
    )

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    source_chunks = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.role.capitalize()}: {self.content[:50]}"
