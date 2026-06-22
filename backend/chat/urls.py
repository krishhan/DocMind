from django.urls import path
from .views import ConversationDetailView

urlpatterns = [
    path('conversations/<int:pk>/', ConversationDetailView.as_view(), name='conversation_detail'),
]
