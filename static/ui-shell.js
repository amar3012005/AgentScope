(function () {
  function byId(id) {
    return document.getElementById(id);
  }

  function resizeComposer(textarea) {
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(Math.max(textarea.scrollHeight, 44), 180)}px`;
  }

  function parseAssistant(raw) {
    const thinkingMatch = raw.match(/<thinking>([\s\S]*?)<\/thinking>/i);
    const thinking = thinkingMatch ? thinkingMatch[1].trim() : '';
    let final = raw.replace(/<thinking>[\s\S]*?<\/thinking>/gi, '').trim();

    final = final.replace(/^\*\*ANSWER\*\*:\s*/i, '').trim();
    final = final.replace(/\*\*CONTEXT\*\*:[\s\S]*$/i, '').trim();
    final = final.replace(/\*\*SOURCES\*\*:[\s\S]*$/i, '').trim();
    final = final.replace(/\*\*CONFIDENCE\*\*:[\s\S]*$/i, '').trim();
    return { thinking, final };
  }

  function makePosterHtml(prompt, page) {
    return `
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BLAIQ Poster</title>
  <style>
    html, body { margin:0; height:100%; font-family: "Sohne", "Manrope", sans-serif; }
    body {
      display:grid; place-items:center;
      background:
        radial-gradient(1200px 500px at 70% -10%, rgba(74,222,128,0.35), transparent 58%),
        linear-gradient(180deg, #070707 0%, #0c0c0c 100%);
      color: #f4f4f5;
    }
    .poster {
      width:min(900px, 92vw);
      border:1px solid #2b2b2b;
      border-radius:28px;
      background:linear-gradient(180deg, rgba(17,17,17,.92), rgba(10,10,10,.96));
      padding:48px;
      box-shadow:0 24px 80px rgba(0,0,0,.45);
    }
    .kicker { color:#86efac; text-transform:uppercase; letter-spacing:.12em; font-size:12px; }
    h1 { margin:14px 0 8px; font-size:64px; line-height:1; letter-spacing:-.04em; }
    p { margin:0; color:#a1a1aa; font-size:20px; line-height:1.5; }
    .foot { margin-top:28px; font-size:14px; color:#d4d4d8; border-top:1px solid #242424; padding-top:16px; }
  </style>
</head>
<body>
  <section class="poster">
    <div class="kicker">BLAIQ / ${page.toUpperCase()}</div>
    <h1>Poster Generated</h1>
    <p>${prompt.replace(/[<>&]/g, '')}</p>
    <div class="foot">Rendered in Vangogh Mode</div>
  </section>
</body>
</html>`.trim();
  }

  function normalizeHtmlArtifact(rawArtifact) {
    let artifact = String(rawArtifact || '');
    const fenceMatch = artifact.match(/```(?:html)?\s*([\s\S]*?)```/i);
    if (fenceMatch && fenceMatch[1]) artifact = fenceMatch[1].trim();
    artifact = artifact.trim();
    if (!artifact) {
      return '<!doctype html><html><body style="margin:0;background:#0b0b0b;color:#f5f5f5;display:grid;place-items:center;font-family:system-ui;"><h1>No HTML artifact</h1></body></html>';
    }
    if (!/<html[\s>]|<body[\s>]|<!doctype/i.test(artifact)) {
      return `<!doctype html><html><body style="margin:0;background:#0b0b0b;color:#f5f5f5;padding:18px;font-family:ui-monospace,monospace;"><pre>${artifact
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')}</pre></body></html>`;
    }
    return artifact;
  }

  function init() {
    const shell = byId('app-shell');
    if (!shell) return;

    const page = shell.dataset.page || 'agents';
    const pageTitle = shell.dataset.title || 'Workspace';

    document.querySelectorAll('[data-nav]').forEach((node) => {
      node.classList.toggle('active', node.dataset.nav === page);
    });

    const topTitle = byId('topbar-title');
    if (topTitle) topTitle.textContent = pageTitle;

    const q = byId('q');
    const send = byId('send');
    const thinking = byId('thinking');
    const answer = byId('answer');
    const userPrompt = byId('user-prompt');
    const previewTitle = byId('preview-title-text');
    const previewLoading = byId('preview-loading');
    const previewFrame = byId('preview-frame');
    const previewPane = byId('preview-pane');

    let rawAssistant = '';
    let latestPreviewHtml = '';

    function openPreview() {
      shell.classList.add('show-preview');
    }

    function closePreview() {
      shell.classList.remove('show-preview');
    }

    function setPreviewLoadingState() {
      openPreview();
      if (previewTitle) previewTitle.textContent = 'Generating content...';
      if (previewLoading) previewLoading.style.display = 'grid';
      if (previewFrame) previewFrame.style.display = 'none';
    }

    function setPreviewContent(html) {
      const normalized = normalizeHtmlArtifact(html);
      latestPreviewHtml = normalized;
      if (previewTitle) previewTitle.textContent = 'Preview live';
      if (previewLoading) previewLoading.style.display = 'none';
      if (previewFrame) {
        previewFrame.style.display = 'block';
        previewFrame.srcdoc = normalized;
      }
      openPreview();
    }

    async function downloadPng() {
      if (!latestPreviewHtml || !previewFrame) return;
      try {
        const iframeDoc = previewFrame.contentDocument || previewFrame.contentWindow?.document;
        const root = iframeDoc.documentElement;
        const width = Math.max(1200, root.scrollWidth || 1200);
        const height = Math.max(1600, root.scrollHeight || 1600);
        const xml = new XMLSerializer().serializeToString(root);
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><foreignObject width="100%" height="100%">${xml}</foreignObject></svg>`;
        const blobUrl = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }));
        const image = new Image();
        await new Promise((resolve, reject) => {
          image.onload = resolve;
          image.onerror = reject;
          image.src = blobUrl;
        });
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext('2d');
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, width, height);
        context.drawImage(image, 0, 0, width, height);
        const link = document.createElement('a');
        link.href = canvas.toDataURL('image/png');
        link.download = `blaiq-${page}-${new Date().toISOString().replace(/[:.]/g, '-')}.png`;
        link.click();
        URL.revokeObjectURL(blobUrl);
      } catch (error) {
        console.error(error);
      }
    }

    function renderAssistant() {
      const parsed = parseAssistant(rawAssistant);
      if (thinking) {
        thinking.style.display = parsed.thinking ? 'block' : 'none';
        thinking.textContent = parsed.thinking;
      }
      if (answer) {
        answer.className = parsed.final ? 'chat-bubble final' : 'chat-bubble';
        answer.textContent = parsed.final || 'Thinking...';
      }
    }

    function simulateReply() {
      const prompt = (q?.value || '').trim();
      if (!prompt) return;
      if (userPrompt) userPrompt.textContent = prompt;
      rawAssistant = '<thinking>Analyzing intent and selecting best subagent route.</thinking>';
      renderAssistant();
      q.value = '';
      resizeComposer(q);

      const wantsPoster = /poster|design|landing|content|generate/i.test(prompt);
      if (wantsPoster) {
        setPreviewLoadingState();
      }

      setTimeout(() => {
        rawAssistant += `\n\nFinal answer: ${wantsPoster ? 'Poster build started in Vangogh mode. The generated output is live in preview.' : 'Request processed. No poster generation was required for this action.'}`;
        renderAssistant();

        if (wantsPoster) {
          setPreviewContent(makePosterHtml(prompt, page));
        }
      }, 650);
    }

    if (q) {
      q.addEventListener('input', () => resizeComposer(q));
      q.addEventListener('keydown', (event) => {
        if (event.isComposing) return;
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          simulateReply();
        }
      });
      resizeComposer(q);
    }

    if (send) send.addEventListener('click', simulateReply);
    const openBtns = ['open-preview', 'top-preview'];
    openBtns.forEach((id) => {
      const node = byId(id);
      if (node) node.addEventListener('click', openPreview);
    });
    const closeBtn = byId('close-preview');
    if (closeBtn) closeBtn.addEventListener('click', closePreview);
    const fullBtn = byId('full-preview');
    if (fullBtn) {
      fullBtn.addEventListener('click', async () => {
        if (!document.fullscreenElement) await previewPane.requestFullscreen();
        else await document.exitFullscreen();
      });
    }
    const downloadBtn = byId('download-preview');
    if (downloadBtn) downloadBtn.addEventListener('click', downloadPng);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
