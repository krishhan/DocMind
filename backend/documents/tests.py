from unittest.mock import patch, MagicMock, mock_open
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Document

class DocumentTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='password123')
        self.upload_url = reverse('document_list_upload')
        
    def test_upload_unauthenticated(self):
        response = self.client.post(self.upload_url, {}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_upload_invalid_file_type(self):
        self.client.force_authenticate(user=self.user)
        txt_file = SimpleUploadedFile("test.txt", b"some dummy text content", content_type="text/plain")
        response = self.client.post(self.upload_url, {'file': txt_file}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    @patch('documents.views.process_document_task')
    def test_upload_success(self, mock_process):
        self.client.force_authenticate(user=self.user)
        pdf_file = SimpleUploadedFile("test.pdf", b"%PDF-1.4 dummy content", content_type="application/pdf")
        response = self.client.post(self.upload_url, {'file': pdf_file}, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Document.objects.count(), 1)
        doc = Document.objects.first()
        self.assertEqual(doc.filename, 'test.pdf')
        self.assertEqual(doc.status, 'processing')
        mock_process.delay.assert_called_once_with(doc.id)

    def test_list_documents(self):
        self.client.force_authenticate(user=self.user)
        Document.objects.create(owner=self.user, filename='doc1.pdf', status='ready', file='documents/doc1.pdf')
        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Handle paginated results key or raw array list
        data = response.data.get('results') if isinstance(response.data, dict) else response.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['filename'], 'doc1.pdf')

    def test_recursive_split_text_utility(self):
        from .utils import split_text_recursively
        text = "This is a paragraph.\n\nThis is a second paragraph. It contains multiple sentences to test."
        chunks = split_text_recursively(text, max_chunk_size=35, overlap=5)
        self.assertTrue(len(chunks) > 0)

    @patch('documents.utils.get_ocr_engine')
    @patch('documents.utils.fitz.open')
    @patch('documents.utils.pypdf.PdfReader')
    @patch('builtins.open', new_callable=mock_open)
    def test_ocr_fallback_triggered(self, mock_file_open, mock_pypdf_reader, mock_fitz_open, mock_get_ocr_engine):
        # Setup mocks
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "" # Digital text is empty
        mock_pypdf_reader.return_value.pages = [mock_page]
        
        # PyMuPDF mock setup
        mock_fitz_page = MagicMock()
        mock_pixmap = MagicMock()
        mock_pixmap.tobytes.return_value = b"fake_png_bytes"
        mock_fitz_page.get_pixmap.return_value = mock_pixmap
        mock_fitz_open.return_value.__getitem__.return_value = mock_fitz_page
        
        # OCR Engine mock setup
        mock_ocr = MagicMock()
        mock_ocr.return_value = (
            [
                [ [[0, 0], [10, 10]], "This is OCR extracted text", 0.99 ]
            ], 
            0.1
        )
        mock_get_ocr_engine.return_value = mock_ocr
        
        from .utils import extract_and_chunk_pdf
        chunks = extract_and_chunk_pdf("fake_path.pdf")
        
        # Assertions
        mock_page.extract_text.assert_called_once()
        mock_fitz_open.assert_called_once_with("fake_path.pdf")
        mock_get_ocr_engine.assert_called_once()
        mock_ocr.assert_called_once_with(b"fake_png_bytes")
        
        # Check that open was called for fake_path.pdf (filtering out tiktoken cache opens)
        fake_path_opened = any(
            call[0][0] == "fake_path.pdf" and call[0][1] == "rb"
            for call in mock_file_open.call_args_list
        )
        self.assertTrue(fake_path_opened, "fake_path.pdf was not opened in read-binary mode.")
        
        # Should successfully extract and chunk the OCR text
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]['text'], "This is OCR extracted text")
        self.assertEqual(chunks[0]['page'], 1)
