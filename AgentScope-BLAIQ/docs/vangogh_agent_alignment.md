# VanGogh Agent Alignment

## Goal

Define `VanGogh` as the visual execution agent in the AgentScope AaaS stack.

The agent should be a thin executor that:

- accepts a render plan
- chooses image or video tool execution
- calls the tool directly
- returns normalized tool output

It should not become a second planner or a compatibility layer for older HTML-driven visual flows.

## Intended Role

`VanGogh` is the rendering node.

Its job is to convert a render plan into:

- an image-generation call
- or a video-generation call

It should not:

- reinterpret the content strategy
- rewrite the poster brief
- synthesize HTML by default for poster artifacts
- generate a second opinion on what the upstream agent already decided

## Official-Style Shape

The closest AgentScope AaaS shape for `VanGogh` is:

1. `AgentApp` exposes the service.
2. `@app.query(framework="agentscope")` is the service entrypoint.
3. A single agent instance handles rendering.
4. `Toolkit` registers tool functions like `generate_image` and `generate_video`.
5. Hooks capture telemetry and lifecycle events.
6. The output is a normalized artifact response, not a full design rewrite.

## What Should Stay

- `AgentApp` service wrapper
- `Toolkit` tool registration
- `generate_image` and `generate_video`
- hooks for telemetry
- a strict render-plan parser
- normalized response wrapping so the rest of the platform can consume media uniformly

## What Should Be Simplified

- Poster and image-first flows should short-circuit directly to tool execution.
- HTML should be treated as a fallback or preview mode, not the default rendering path for poster artifacts.
- The render plan contract should determine execution mode, not hidden heuristics.

## What Should Be Removed

- dual-path logic that tries to behave like both a renderer and a layout author
- HTML synthesis for poster artifacts when the upstream plan already chose image generation
- JSON parsing of tool output that forces the tool response back through an LLM-shaped rewrite
- legacy compatibility assumptions that keep old render modes alive without clear business need

## Cleanup Plan

1. Make image-first routing explicit in the render-plan schema.
2. Remove poster-specific HTML synthesis from the main path.
3. Keep the agent as a direct media tool executor.
4. Normalize image/video payloads in one adapter only.
5. Retain HTML preview only as a secondary artifact format for non-image-first flows.

## Alignment Criteria

`VanGogh` is aligned when:

- posters always go straight to `generate_image`
- video requests always go straight to `generate_video`
- the agent does not co-author the visual spec
- the tool output is passed through with minimal transformation
- the rest of BLAIQ consumes one stable visual artifact contract

