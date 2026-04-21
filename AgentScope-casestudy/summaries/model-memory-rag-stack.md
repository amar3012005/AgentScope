# model-memory-rag-stack

This note groups the core model layer with context, memory, and retrieval.

## Covered docs

- [Model](https://docs.agentscope.io/basic-concepts/model)
- [Context and Memory](https://docs.agentscope.io/basic-concepts/context-and-memory)
- [Building-blocks context and memory](https://docs.agentscope.io/building-blocks/context-and-memory)
- [Models](https://docs.agentscope.io/building-blocks/models)
- [RAG](https://docs.agentscope.io/building-blocks/rag)

## Main themes

- The model layer is provider-agnostic and covers chat, streaming, reasoning, tools API, TTS, realtime, and embeddings.
- Context is inference-time input; short-term memory is session state; long-term memory persists across sessions.
- The implementation docs show how memory backends and long-term memory connect to agent workflows.
- RAG is the retrieval layer that gives the agent external knowledge beyond the conversation buffer.

## Practical reading order

1. Read `basic-concepts/model` for the abstraction layer.
2. Read `basic-concepts/context-and-memory` for the conceptual split.
3. Read `building-blocks/context-and-memory` for concrete memory backends.
4. Read `building-blocks/rag` for retrieval-backed agent design.
