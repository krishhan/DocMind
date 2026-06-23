from unittest.mock import patch, MagicMock
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from documents.models import Document
from chat.models import Conversation, Message

class ChatTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='password123')
        self.document = Document.objects.create(
            owner=self.user,
            filename='sample.pdf',
            status='ready',
            file='documents/sample.pdf'
        )
        self.ask_url = reverse('document_ask', kwargs={'pk': self.document.id})
        self.convo_url = reverse('document_conversations', kwargs={'pk': self.document.id})

    def test_list_conversations_unauthenticated(self):
        response = self.client.get(self.convo_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_conversation(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.convo_url, {'title': 'My Chat'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Conversation.objects.first().title, 'My Chat')

    def test_ask_rate_limit(self):
        self.client.force_authenticate(user=self.user)
        convo = Conversation.objects.create(document=self.document, user=self.user, title='Test Convo')
        
        # Populate 20 queries today
        for i in range(20):
            Message.objects.create(conversation=convo, role='user', content=f'Q{i}')
            Message.objects.create(conversation=convo, role='assistant', content=f'A{i}')

        # The 21st question should exceed the daily rate limit
        response = self.client.post(self.ask_url, {'question': 'How are you?', 'conversation_id': convo.id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn('limit exceeded', response.data['error'])

    @patch('chat.views.get_embedding_model')
    @patch('chat.views.get_chroma_collection')
    @patch('chat.views.OpenAI')
    @patch('chat.views.os.environ.get')
    def test_ask_success(self, mock_env_get, mock_openai_cls, mock_chroma_col, mock_get_embedding):
        self.client.force_authenticate(user=self.user)
        
        # Populate DocumentChunk in SQLite for BM25 matching
        from documents.models import DocumentChunk
        DocumentChunk.objects.create(
            document=self.document,
            chunk_text="This is page 1 context text containing standard keyword JWT.",
            chunk_index=0,
            page_number=1,
            vector_id="doc_1_chunk_0"
        )
        
        # Set environment variables mock
        mock_env_get.side_effect = lambda key, default=None: {
            "OPENROUTER_API_KEY": "fake_key",
            "OPENROUTER_MODEL": "meta-llama/llama-3.1-8b-instruct:free"
        }.get(key, default)

        # Mock embedding model
        mock_model = MagicMock()
        mock_model.encode.return_value = [0.1, 0.2, 0.3]
        mock_get_embedding.return_value = mock_model

        # Mock ChromaDB query output
        mock_col = MagicMock()
        mock_col.query.return_value = {
            'documents': [['This is page 1 context text containing standard keyword JWT.']],
            'metadatas': [[{'page_number': 1, 'document_id': self.document.id}]]
        }
        mock_chroma_col.return_value = mock_col

        # Mock OpenAI Client completions
        mock_client = MagicMock()
        
        # We need chunk objects that can be iterated over
        class MockDelta:
            def __init__(self, content):
                self.content = content

        class MockChoice:
            def __init__(self, content):
                self.delta = MockDelta(content)

        class MockChunk:
            def __init__(self, content):
                self.choices = [MockChoice(content)]

        chunks = [
            MockChunk("This is the "),
            MockChunk("generated answer based "),
            MockChunk("on page 1.")
        ]
        mock_client.chat.completions.create.return_value = chunks
        mock_openai_cls.return_value = mock_client

        # Perform request using keyword to trigger BM25 scoring
        response = self.client.post(self.ask_url, {'question': 'What is JWT?'}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Read the streaming content
        content_chunks = list(response.streaming_content)
        decoded_content = [c.decode('utf-8') if isinstance(c, bytes) else c for c in content_chunks]
        full_stream_text = "".join(decoded_content)
        
        # Verify the SSE format
        self.assertIn("event: sources", full_stream_text)
        self.assertIn("event: message", full_stream_text)
        self.assertIn("page_number", full_stream_text)
        self.assertIn("This is the", full_stream_text)
        self.assertIn("generated answer based", full_stream_text)
        self.assertIn("on page 1.", full_stream_text)
        
        # Verify database objects
        self.assertEqual(Conversation.objects.count(), 1)
        convo = Conversation.objects.first()
        messages = Message.objects.filter(conversation=convo).order_by('created_at')
        # There should be 2 messages (1 user, 1 assistant)
        self.assertEqual(messages.count(), 2)
        self.assertEqual(messages[0].role, 'user')
        self.assertEqual(messages[0].content, 'What is JWT?')
        self.assertEqual(messages[1].role, 'assistant')
        self.assertEqual(messages[1].content, "This is the generated answer based on page 1.")

    def test_rename_conversation(self):
        self.client.force_authenticate(user=self.user)
        convo = Conversation.objects.create(document=self.document, user=self.user, title='Old Title')
        
        detail_url = reverse('conversation_detail', kwargs={'pk': convo.id})
        response = self.client.patch(detail_url, {'title': 'New Renamed Title'}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        convo.refresh_from_db()
        self.assertEqual(convo.title, 'New Renamed Title')

    def test_delete_conversation(self):
        self.client.force_authenticate(user=self.user)
        convo = Conversation.objects.create(document=self.document, user=self.user, title='To Be Deleted')
        
        detail_url = reverse('conversation_detail', kwargs={'pk': convo.id})
        response = self.client.delete(detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Conversation.objects.filter(id=convo.id).count(), 0)

    @patch('chat.views.get_embedding_model')
    @patch('chat.views.get_chroma_collection')
    @patch('chat.views.OpenAI')
    @patch('chat.views.os.environ.get')
    def test_ask_with_long_history(self, mock_env_get, mock_openai_cls, mock_chroma_col, mock_get_embedding):
        self.client.force_authenticate(user=self.user)
        convo = Conversation.objects.create(document=self.document, user=self.user, title='Long Chat')
        
        # Create 15 messages (Message 0 to Message 14)
        for i in range(15):
            role = 'user' if i % 2 == 0 else 'assistant'
            Message.objects.create(conversation=convo, role=role, content=f'Message {i}')
            
        mock_env_get.side_effect = lambda key, default=None: {
            "OPENROUTER_API_KEY": "fake_key"
        }.get(key, default)

        # Mock embedding and chroma
        mock_model = MagicMock()
        mock_model.encode.return_value = [0.1] * 384
        mock_get_embedding.return_value = mock_model
        
        mock_col = MagicMock()
        mock_col.query.return_value = {'documents': [[]], 'metadatas': [[]]}
        mock_chroma_col.return_value = mock_col

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = []
        mock_openai_cls.return_value = mock_client
        
        # Make the request
        response = self.client.post(self.ask_url, {
            'question': 'Next Question',
            'conversation_id': convo.id
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Consume the streaming content to trigger generator execution
        list(response.streaming_content)
        
        # Verify that mock_client.chat.completions.create was called with the correct history
        call_args = mock_client.chat.completions.create.call_args
        self.assertIsNotNone(call_args)
        called_messages = call_args[1]['messages']
        
        # called_messages[0] is system prompt, called_messages[-1] is user prompt
        # the middle slice should contain messages 5 to 14
        history = called_messages[1:-1]
        self.assertEqual(len(history), 10)
        self.assertEqual(history[0]['content'], 'Message 5')
        self.assertEqual(history[-1]['content'], 'Message 14')
