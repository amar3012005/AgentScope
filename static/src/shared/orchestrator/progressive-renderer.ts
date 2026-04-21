/**
 * Progressive renderer for Vangogh V2 artifacts.
 *
 * Incrementally appends section HTML fragments to an iframe's DOM
 * instead of replacing the entire srcDoc on each update.
 */
export class ProgressiveRenderer {
  private iframe: HTMLIFrameElement;
  private initialized = false;

  constructor(iframe: HTMLIFrameElement) {
    this.iframe = iframe;
  }

  /**
   * Initialize the iframe with the base document shell.
   * Must be called once before appendSection.
   */
  initialize(baseShellHtml: string): void {
    this.iframe.srcdoc = baseShellHtml;
    this.initialized = true;
  }

  /**
   * Wait for the iframe to finish loading after initialize().
   */
  waitForLoad(): Promise<void> {
    return new Promise((resolve) => {
      if (!this.iframe.contentDocument?.body) {
        this.iframe.addEventListener("load", () => resolve(), { once: true });
      } else {
        resolve();
      }
    });
  }

  /**
   * Append a section HTML fragment to the iframe's vangogh-root.
   */
  appendSection(sectionId: string, htmlFragment: string): void {
    const doc = this.iframe.contentDocument;
    if (!doc) return;

    let root = doc.getElementById("vangogh-root");
    if (!root) {
      // Fallback: create vangogh-root if it doesn't exist
      root = doc.createElement("div");
      root.id = "vangogh-root";
      doc.body.appendChild(root);
    }

    const wrapper = doc.createElement("div");
    wrapper.id = `section-${sectionId}`;
    wrapper.className = "vangogh-section";
    wrapper.innerHTML = htmlFragment;
    root.appendChild(wrapper);

    // Re-initialize charts and mermaid for new elements
    this.initDynamicContent(doc, wrapper);
  }

  /**
   * Replace an existing section's HTML (for section-level regeneration).
   */
  replaceSection(sectionId: string, htmlFragment: string): void {
    const doc = this.iframe.contentDocument;
    if (!doc) return;

    const existing = doc.getElementById(`section-${sectionId}`);
    if (existing) {
      existing.innerHTML = htmlFragment;
      this.initDynamicContent(doc, existing);
    }
  }

  /**
   * Scroll the iframe to a specific section.
   */
  scrollToSection(sectionId: string): void {
    const doc = this.iframe.contentDocument;
    if (!doc) return;

    const target = doc.getElementById(`section-${sectionId}`);
    if (target) {
      target.scrollIntoView({ behavior: "smooth" });
    }
  }

  /**
   * Navigate to a specific slide (for deck/keynote artifacts).
   */
  navigateToSlide(slideIndex: number): void {
    this.iframe.contentWindow?.postMessage(
      { type: "navigate-slide", slideIndex: slideIndex + 1 },
      "*"
    );
  }

  /**
   * Initialize Chart.js and Mermaid for newly added elements.
   */
  private initDynamicContent(_doc: Document, container: HTMLElement): void {
    // Trigger the init function defined in base.html.j2
    const win = this.iframe.contentWindow as Window & { initVangoghCharts?: (el: HTMLElement) => void };
    if (win?.initVangoghCharts) {
      try {
        win.initVangoghCharts(container);
      } catch {
        // Charts/Mermaid may not be loaded yet
      }
    }
  }

  /**
   * Get the current state: whether initialized and section count.
   */
  get sectionCount(): number {
    const doc = this.iframe.contentDocument;
    if (!doc) return 0;
    const root = doc.getElementById("vangogh-root");
    return root?.children.length ?? 0;
  }

  get isInitialized(): boolean {
    return this.initialized;
  }
}
