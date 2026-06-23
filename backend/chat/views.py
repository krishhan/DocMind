import os
import logging
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import status, permissions, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from openai import OpenAI

from documents.models import Document, DocumentChunk
from documents.utils import get_embedding_model, get_chroma_collection
from .models import Conversation, Message
from .serializers import ConversationSerializer, ConversationDetailSerializer, MessageSerializer

logger = logging.getLogger(__name__)

class DocumentConversationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk, *args, **kwargs):
        # List all conversations for the document and user
        document = get_object_or_404(Document, id=pk, owner=request.user)
        conversations = Conversation.objects.filter(document=document, user=request.user).order_by('-created_at')
        serializer = ConversationSerializer(conversations, many=True)
        return Response(serializer.data)

    def post(self, request, pk, *args, **kwargs):
        # Create a new conversation for this document
        document = get_object_or_404(Document, id=pk, owner=request.user)
        title = request.data.get('title', 'New Conversation')
        conversation = Conversation.objects.create(
            document=document,
            user=request.user,
            title=title
        )
        serializer = ConversationSerializer(conversation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class ConversationDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ConversationDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Conversation.objects.filter(user=self.request.user)

class DocumentAskView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, *args, **kwargs):
        # 1. Rate Limiting Check: Max 20 queries/day per user
        one_day_ago = timezone.now() - timedelta(days=1)
        daily_queries = Message.objects.filter(
            conversation__user=request.user,
            role='user',
            created_at__gte=one_day_ago
        ).count()

        if daily_queries >= 20:
            return Response(
                {"error": "Daily rate limit exceeded. You are limited to 20 questions per day."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # 2. Fetch Document
        document = get_object_or_404(Document, id=pk, owner=request.user)
        if document.status != 'ready':
            return Response(
                {"error": f"Document is not ready. Current status: {document.status}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        question = request.data.get('question')
        if not question or not question.strip():
            return Response(
                {"error": "Question parameter is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        conversation_id = request.data.get('conversation_id')
        if conversation_id:
            conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user, document=document)
        else:
            title = question[:50] + ("..." if len(question) > 50 else "")
            conversation = Conversation.objects.create(
                document=document,
                user=request.user,
                title=title
            )

        # 3. Retrieve context using Hybrid Search (Semantic + Lexical BM25)
        try:
            # A. Semantic Search via ChromaDB
            semantic_chunks = []
            try:
                model = get_embedding_model()
                vector_res = model.encode(question)
                question_vector = vector_res.tolist() if hasattr(vector_res, 'tolist') else list(vector_res)

                collection = get_chroma_collection()
                semantic_results = collection.query(
                    query_embeddings=[question_vector],
                    n_results=5,
                    where={"document_id": document.id}
                )
                
                # Extract semantic chunks
                if semantic_results and semantic_results.get('documents') and len(semantic_results['documents']) > 0:
                    texts = semantic_results['documents'][0]
                    metadatas = semantic_results['metadatas'][0]
                    for idx, (text, meta) in enumerate(zip(texts, metadatas)):
                        semantic_chunks.append({
                            "text": text,
                            "page_number": meta.get('page_number', 1),
                            "rank": idx + 1
                        })
            except Exception as semantic_err:
                logger.warning(f"Semantic search failed (using lexical fallback): {str(semantic_err)}")
            
            # B. Lexical Search via BM25
            from rank_bm25 import BM25Okapi
            import re
            
            # Fetch all chunks of the document from SQLite
            db_chunks = DocumentChunk.objects.filter(document=document).order_by('chunk_index')
            lexical_chunks = []
            
            if db_chunks.exists():
                corpus_texts = [chunk.chunk_text for chunk in db_chunks]
                def tokenize(text):
                    return re.findall(r'\w+', text.lower())
                
                tokenized_corpus = [tokenize(t) for t in corpus_texts]
                bm25 = BM25Okapi(tokenized_corpus)
                
                tokenized_query = tokenize(question)
                scores = bm25.get_scores(tokenized_query)
                
                scored_chunks = sorted(
                    zip(db_chunks, scores),
                    key=lambda x: x[1],
                    reverse=True
                )
                
                # Take top 5 with non-zero scores
                for idx, (chunk, score) in enumerate(scored_chunks[:5]):
                    if score > 0.0:
                        lexical_chunks.append({
                            "text": chunk.chunk_text,
                            "page_number": chunk.page_number,
                            "rank": idx + 1
                        })
            
            # C. Reciprocal Rank Fusion (RRF)
            # Combine scores using RRF: score = 1 / (60 + rank_semantic) + 1 / (60 + rank_lexical)
            rrf_scores = {}
            chunk_metadata = {}
            
            # Process Semantic ranks
            for item in semantic_chunks:
                text = item['text']
                rrf_scores[text] = rrf_scores.get(text, 0) + (1.0 / (60.0 + item['rank']))
                chunk_metadata[text] = {"page_number": item['page_number']}
                
            # Process Lexical ranks
            for item in lexical_chunks:
                text = item['text']
                rrf_scores[text] = rrf_scores.get(text, 0) + (1.0 / (60.0 + item['rank']))
                chunk_metadata[text] = {"page_number": item['page_number']}
                
            # Sort combined results by RRF score descending
            merged_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
            final_chunks = merged_results[:5]
            
        except Exception as e:
            logger.exception("Hybrid context retrieval failed")
            return Response(
                {"error": f"Failed to search context: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 4. Format context and source citations
        context = ""
        sources = []
        
        for text, rrf_score in final_chunks:
            meta = chunk_metadata[text]
            page_num = meta["page_number"]
            context += f"--- Page {page_num} ---\n{text}\n\n"
            sources.append({
                "page_number": page_num,
                "text": text
            })

        # 5. OpenRouter LLM Call via OpenAI client
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return Response(
                {"error": "OpenRouter API key is not configured on the backend server. Please add it to your .env file."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        model_name = os.environ.get("OPENROUTER_MODEL", "openrouter/free")
        
        # Load conversation history for context (up to last 10 messages)
        past_msgs = conversation.messages.order_by('-created_at')[:10]
        past_msgs = list(reversed(past_msgs))
        
        messages = [
            {
                "role": "system",
                "content": (
                    "You are DocMind, a precise document Q&A assistant. "
                    "Analyze the provided document context fragments and answer the user's question. "
                    "Ground your answers strictly in the context. "
                    "If the answer cannot be found in the context, state that the document does not contain that information. "
                    "Cite relevant pages in your answer (e.g. 'on page 3...')."
                )
            }
        ]

        for msg in past_msgs:
            messages.append({"role": msg.role, "content": msg.content})

        # Inject context with current question
        user_prompt = f"Here is the document context:\n\n{context}\n\nQuestion: {question}"
        messages.append({"role": "user", "content": user_prompt})

        # 6. Return Streaming response
        from django.http import StreamingHttpResponse
        import json
        
        # Save user's question first so it's captured in DB immediately
        Message.objects.create(
            conversation=conversation,
            role='user',
            content=question
        )

        def event_stream():
            collected_chunks = []
            try:
                client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=api_key,
                )
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    stream=True,
                    timeout=30.0,
                    extra_headers={
                        "HTTP-Referer": "http://localhost:3000",
                        "X-Title": "DocMind",
                    }
                )
                
                # First event: Send conversation details and source citations
                metadata = {
                    "conversation_id": conversation.id,
                    "conversation_title": conversation.title,
                    "sources": sources
                }
                yield f"event: sources\ndata: {json.dumps(metadata)}\n\n"
                
                # Stream the completion tokens
                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        content = chunk.choices[0].delta.content
                        if content:
                            collected_chunks.append(content)
                            yield f"event: message\ndata: {content}\n\n"
                            
            except Exception as e:
                logger.exception("OpenRouter LLM streaming API invocation failed")
                yield f"event: error\ndata: {str(e)}\n\n"
                return
            
            # Save assistant message to database after generator finishes successfully
            full_answer = "".join(collected_chunks)
            if full_answer:
                Message.objects.create(
                    conversation=conversation,
                    role='assistant',
                    content=full_answer,
                    source_chunks=sources
                )

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')
