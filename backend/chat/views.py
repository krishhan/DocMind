import os
import re
import json
import time
import logging
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse
from django.db import transaction, models
from rest_framework import status, permissions, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from openai import OpenAI

from documents.models import Document, DocumentChunk
from documents.serializers import DocumentSerializer
from documents.utils import (
    get_embedding_model, get_chroma_collection, get_reranker_model, get_token_count
)
from docmind.logging_middleware import get_log_context
from .models import Conversation, Message
from .serializers import ConversationSerializer, ConversationDetailSerializer, MessageSerializer

logger = logging.getLogger(__name__)

def is_query_ambiguous(question: str) -> bool:
    question_lower = question.lower()
    # Check for common pronouns
    pronouns = {'it', 'its', 'he', 'him', 'his', 'she', 'her', 'they', 'them', 'their', 'theirs', 'this', 'that', 'these', 'those'}
    words = re.findall(r'\b\w+\b', question_lower)
    if any(word in pronouns for word in words):
        return True
    
    # Check for common ambiguous phrases
    ambiguous_patterns = [
        r'\b(what|who|where|how|why|when) did (he|she|it|they)\b',
        r'\b(explain|summarize|detail|describe) (it|that|this|them)\b',
        r'\b(tell me|give me|show me) more\b',
        r'\b(what is|what are) (the|its|their) (date|schedules|timeline|details|topic|content)\b'
    ]
    for pattern in ambiguous_patterns:
        if re.search(pattern, question_lower):
            return True
            
    return False

def rewrite_query_with_history(question, past_messages, api_key, model_name):
    # Skip rewriting if no history or query is not ambiguous
    if not past_messages or not is_query_ambiguous(question):
        logger.info(f"Skipping query rewrite for question: '{question}'")
        return question

    # Assemble the last ~1500 tokens of history
    history_messages = []
    total_tokens = 0
    for msg in reversed(past_messages):
        msg_tokens = get_token_count(msg.content)
        if total_tokens + msg_tokens > 1500:
            break
        history_messages.insert(0, msg)
        total_tokens += msg_tokens

    history_str = ""
    for msg in history_messages:
        history_str += f"{msg.role.capitalize()}: {msg.content}\n"

    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        prompt = (
            f"Conversation History:\n{history_str}\n"
            f"Follow-up Query: {question}\n\n"
            f"Based on the conversation history, rewrite the follow-up query to be a standalone, self-contained search query. "
            f"If the query is already self-contained or cannot be rewritten, return it exactly as-is. "
            f"Return ONLY the rewritten query text and absolutely nothing else."
        )
        fallback_models = [
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemma-4-31b-it:free",
            "qwen/qwen3-next-80b-a3b-instruct:free",
            "google/gemma-4-26b-a4b-it:free",
            "openai/gpt-oss-120b:free"
        ]
        models_list = [model_name]
        for m in fallback_models:
            if m not in models_list:
                models_list.append(m)

        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a precise search query rewriter. Output only the rewritten query and nothing else."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=100,
            temperature=0.0,
            extra_body={
                "models": models_list
            }
        )
        rewritten = response.choices[0].message.content.strip()
        if rewritten:
            logger.info(f"Query rewritten: '{question}' -> '{rewritten}'")
            return rewritten
    except Exception as e:
        logger.error(f"Failed to rewrite query: {str(e)}")
    return question


class DocumentConversationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk, *args, **kwargs):
        # List all conversations for the document and user
        document = get_object_or_404(Document, id=pk, owner=request.user)
        # Filter conversations where either 'document' matches or it's linked in 'documents' M2M
        conversations = Conversation.objects.filter(
            user=request.user
        ).filter(
            models.Q(document=document) | models.Q(documents=document)
        ).distinct().select_related('document', 'user').order_by('-created_at')
        serializer = ConversationSerializer(conversations, many=True)
        return Response(serializer.data)

    def post(self, request, pk, *args, **kwargs):
        # Create a new conversation for this document
        document = get_object_or_404(Document, id=pk, owner=request.user)
        title = request.data.get('title', 'New Conversation')
        with transaction.atomic():
            conversation = Conversation.objects.create(
                document=document,
                user=request.user,
                title=title
            )
            # Add to ManyToMany documents list for compatibility
            conversation.documents.add(document)
        serializer = ConversationSerializer(conversation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ConversationDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ConversationDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Conversation.objects.filter(user=self.request.user).prefetch_related('messages')


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

        question = request.data.get('question')
        if not question or not question.strip():
            return Response(
                {"error": "Question parameter is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        conversation_id = request.data.get('conversation_id')
        document_ids = request.data.get('document_ids', []) # Optional list of doc IDs for multi-doc chat

        # 2. Fetch/Create Conversation and Link Active Documents
        with transaction.atomic():
            if conversation_id:
                conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
                # Link newly selected documents if provided
                if document_ids:
                    linked_docs = Document.objects.filter(id__in=document_ids, owner=request.user)
                    conversation.documents.set(linked_docs)
            else:
                title = question[:50] + ("..." if len(question) > 50 else "")
                conversation = Conversation.objects.create(
                    user=request.user,
                    title=title
                )
                if document_ids:
                    linked_docs = Document.objects.filter(id__in=document_ids, owner=request.user)
                    conversation.documents.set(linked_docs)
                    if linked_docs.exists():
                        conversation.document = linked_docs.first()
                        conversation.save()
                else:
                    doc = get_object_or_404(Document, id=pk, owner=request.user)
                    conversation.documents.set([doc])
                    conversation.document = doc
                    conversation.save()

        # 3. Retrieve context and compile documents mapping
        active_docs = list(conversation.documents.filter(status='ready'))
        if not active_docs and conversation.document and conversation.document.status == 'ready':
            active_docs = [conversation.document]

        if not active_docs:
            return Response(
                {"error": "No indexed documents are linked to this conversation or ready to chat."},
                status=status.HTTP_400_BAD_REQUEST
            )

        doc_names = {d.id: d.filename for d in active_docs}

        # 4. Trigger Query Rewriter (if history exists)
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return Response(
                {"error": "OpenRouter API key is not configured. Please add it to your .env file."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        model_name = os.environ.get("OPENROUTER_MODEL", "openrouter/free")
        
        past_msgs = list(conversation.messages.order_by('-created_at')[:15])
        search_query = rewrite_query_with_history(question, list(reversed(past_msgs)), api_key, model_name)

        # 5. Hybrid Search Retrieval
        retrieval_start = time.time()
        
        # A. Semantic Search via ChromaDB
        semantic_chunks = []
        try:
            model = get_embedding_model()
            vector_res = model.encode(search_query)
            query_vector = vector_res.tolist() if hasattr(vector_res, 'tolist') else list(vector_res)

            collection = get_chroma_collection()
            # Build Chroma where filter for document IDs
            if len(active_docs) > 1:
                where_filter = {"document_id": {"$in": [d.id for d in active_docs]}}
            else:
                where_filter = {"document_id": active_docs[0].id}

            semantic_results = collection.query(
                query_embeddings=[query_vector],
                n_results=10,
                where=where_filter
            )
            
            if semantic_results and semantic_results.get('documents') and len(semantic_results['documents']) > 0:
                texts = semantic_results['documents'][0]
                metadatas = semantic_results['metadatas'][0]
                distances = semantic_results['distances'][0] if ('distances' in semantic_results and semantic_results['distances']) else [0.0]*len(texts)
                ids = semantic_results['ids'][0] if ('ids' in semantic_results and semantic_results['ids']) else [f"sem_chunk_{i}" for i in range(len(texts))]
                
                for idx, (vid, text, meta, dist) in enumerate(zip(ids, texts, metadatas, distances)):
                    semantic_chunks.append({
                        "vector_id": vid,
                        "text": text,
                        "page_number": meta.get('page_number', 1),
                        "document_id": meta.get('document_id'),
                        "heading": meta.get('heading', ''),
                        "section": meta.get('section', ''),
                        "token_count": meta.get('token_count', 0),
                        "distance": dist,
                        "rank": idx + 1
                    })
        except Exception as semantic_err:
            logger.warning(f"Semantic search failed: {str(semantic_err)}")
        
        # B. Lexical Search via BM25 across all documents' SQLite chunks
        lexical_chunks = []
        try:
            db_chunks = DocumentChunk.objects.filter(document__in=active_docs).select_related('document').order_by('chunk_index')
            if db_chunks.exists():
                corpus_texts = [chunk.chunk_text for chunk in db_chunks]
                
                def tokenize(text):
                    return re.findall(r'\w+', text.lower())
                
                tokenized_corpus = [tokenize(t) for t in corpus_texts]
                from rank_bm25 import BM25Okapi
                bm25 = BM25Okapi(tokenized_corpus)
                
                tokenized_query = tokenize(search_query)
                scores = bm25.get_scores(tokenized_query)
                
                scored_chunks = sorted(
                    zip(db_chunks, scores),
                    key=lambda x: x[1],
                    reverse=True
                )
                
                # Retrieve top 10 lexical results with positive score
                for idx, (chunk, score) in enumerate(scored_chunks[:10]):
                    if score > 0.0:
                        lexical_chunks.append({
                            "vector_id": chunk.vector_id,
                            "text": chunk.chunk_text,
                            "page_number": chunk.page_number,
                            "document_id": chunk.document.id,
                            "heading": chunk.heading or '',
                            "section": chunk.section or '',
                            "token_count": chunk.token_count,
                            "score": score,
                            "rank": idx + 1
                        })
        except Exception as lexical_err:
            logger.warning(f"Lexical search failed: {str(lexical_err)}")

        # C. Reciprocal Rank Fusion (RRF)
        rrf_scores = {}
        chunk_map = {}
        
        # Process Semantic ranks
        for item in semantic_chunks:
            vid = item['vector_id']
            rrf_scores[vid] = rrf_scores.get(vid, 0.0) + (1.0 / (60.0 + item['rank']))
            chunk_map[vid] = item
            
        # Process Lexical ranks
        for item in lexical_chunks:
            vid = item['vector_id']
            rrf_scores[vid] = rrf_scores.get(vid, 0.0) + (1.0 / (60.0 + item['rank']))
            if vid not in chunk_map:
                chunk_map[vid] = item
            else:
                chunk_map[vid]['score'] = item['score']
                chunk_map[vid]['lexical_rank'] = item['rank']

        # Sort candidates by RRF score descending
        merged_candidates = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)
        top_candidates = [chunk_map[vid] for vid in merged_candidates[:15]]
        
        retrieval_duration = time.time() - retrieval_start

        # 6. Optional Cross-Encoder Reranker
        enable_reranker = os.environ.get('ENABLE_RERANKER', 'False').lower() in ('true', '1', 'yes')
        rerank_start = time.time()
        rerank_duration = 0.0
        
        if enable_reranker and len(top_candidates) > 0:
            try:
                reranker = get_reranker_model()
                pairs = [[search_query, c['text']] for c in top_candidates]
                scores = reranker.predict(pairs)
                
                for c, score in zip(top_candidates, scores):
                    c['rerank_score'] = float(score)
                
                top_candidates = sorted(top_candidates, key=lambda x: x['rerank_score'], reverse=True)
                logger.info(f"Reranked {len(top_candidates)} chunks successfully.")
            except Exception as rerank_err:
                logger.error(f"CrossEncoder reranking failed: {str(rerank_err)}")
            rerank_duration = time.time() - rerank_start

        final_chunks = top_candidates[:5]

        # 7. Format context, metrics, and citations
        context = ""
        sources = []
        
        for c in final_chunks:
            doc_name = doc_names.get(c['document_id'], "Unknown Document")
            context += f"--- Document: {doc_name}, Page {c['page_number']} ---\n{c['text']}\n\n"
            
            # Map metrics
            retrieval_method = "hybrid"
            if 'rank' in c and 'lexical_rank' in c:
                retrieval_method = "hybrid"
            elif 'rank' in c:
                retrieval_method = "semantic"
            else:
                retrieval_method = "lexical"

            score = c.get('rerank_score')
            if score is None:
                if 'distance' in c:
                    score = 1.0 - c['distance']
                else:
                    score = c.get('score', 0.0)

            sources.append({
                "similarity_score": score,
                "retrieval_method": retrieval_method,
                "page_number": c['page_number'],
                "document_id": c['document_id'],
                "document_name": doc_name,
                "chunk_id": c['vector_id'],
                "text": c['text']
            })

        # Set up structured logging middleware metrics
        log_ctx = get_log_context()
        log_ctx['document_id'] = active_docs[0].id if len(active_docs) == 1 else None
        log_ctx['conversation_id'] = conversation.id
        log_ctx['retrieval_duration'] = retrieval_duration
        if enable_reranker:
            log_ctx['rerank_duration'] = rerank_duration

        # Assemble chat prompts, keeping history within ~1500 tokens
        history_messages = []
        history_tokens = 0
        for msg in past_msgs:
            msg_tokens = get_token_count(msg.content)
            if history_tokens + msg_tokens > 1500:
                break
            history_messages.append(msg)
            history_tokens += msg_tokens
            
        history_messages = list(reversed(history_messages))

        messages = [
            {
                "role": "system",
                "content": (
                    "You are DocMind, a precise document Q&A assistant. "
                    "Analyze the provided document context fragments and answer the user's question. "
                    "Ground your answers strictly in the context. "
                    "If the answer cannot be found in the context, state that the document(s) do not contain that information. "
                    "Cite relevant documents and page numbers in your answer (e.g. '[Document Name] on page 3')."
                )
            }
        ]
        
        for msg in history_messages:
            messages.append({"role": msg.role, "content": msg.content})
            
        messages.append({"role": "user", "content": f"Here is the document context:\n\n{context}\n\nQuestion: {question}"})

        # Save user message immediately to the database
        Message.objects.create(
            conversation=conversation,
            role='user',
            content=question
        )

        def event_stream():
            collected_chunks = []
            llm_start = time.time()
            try:
                client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=api_key,
                )
                fallback_models = [
                    "meta-llama/llama-3.3-70b-instruct:free",
                    "google/gemma-4-31b-it:free",
                    "qwen/qwen3-next-80b-a3b-instruct:free",
                    "google/gemma-4-26b-a4b-it:free",
                    "openai/gpt-oss-120b:free"
                ]
                models_list = [model_name]
                for m in fallback_models:
                    if m not in models_list:
                        models_list.append(m)

                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    stream=True,
                    timeout=30.0,
                    extra_headers={
                        "HTTP-Referer": "http://localhost:3000",
                        "X-Title": "DocMind",
                    },
                    extra_body={
                        "models": models_list
                    }
                )
                
                # Event 1: Stream metadata & sources grouped
                metadata = {
                    "conversation_id": conversation.id,
                    "conversation_title": conversation.title,
                    "sources": sources
                }
                yield f"event: sources\ndata: {json.dumps(metadata)}\n\n"
                
                # Event 2: Stream text tokens in a JSON-safe wrapper
                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        content = chunk.choices[0].delta.content
                        if content:
                            collected_chunks.append(content)
                            yield f"event: message\ndata: {json.dumps({'text': content})}\n\n"
                
                # Event 3: Done event
                llm_duration = time.time() - llm_start
                yield f"event: done\ndata: {json.dumps({'status': 'completed', 'llm_duration': llm_duration})}\n\n"
                
            except Exception as e:
                logger.exception("OpenRouter LLM streaming failed")
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                return
            
            # Save Assistant message once generator completes
            full_answer = "".join(collected_chunks)
            if full_answer:
                with transaction.atomic():
                    Message.objects.create(
                        conversation=conversation,
                        role='assistant',
                        content=full_answer,
                        source_chunks=sources
                    )

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')
