from django.urls import path
from .views import DocumentListUploadView, DocumentDetailView
# Import views from chat application to mount them under the document paths
from chat.views import DocumentAskView, DocumentConversationsView

urlpatterns = [
    path('', DocumentListUploadView.as_view(), name='document_list_upload'),
    path('<int:pk>/', DocumentDetailView.as_view(), name='document_detail'),
    path('<int:pk>/ask/', DocumentAskView.as_view(), name='document_ask'),
    path('<int:pk>/conversations/', DocumentConversationsView.as_view(), name='document_conversations'),
]
