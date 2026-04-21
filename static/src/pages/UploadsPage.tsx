import { useCallback } from "react";
import { useOrchestratorStore } from "../shared/orchestrator/store";

export function UploadsPage() {
  const { state, uploadFiles } = useOrchestratorStore();

  const handleFileSelection = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? []);
      if (files.length === 0) {
        return;
      }
      await uploadFiles(files);
      event.target.value = "";
    },
    [uploadFiles],
  );

  return (
    <section className="detail-grid">
      <section className="panel-card">
        <div className="panel-card__header">
          <span>Knowledge uploads</span>
          <label className="topbar-shell__button topbar-shell__button--primary">
            Add documents
            <input type="file" multiple hidden onChange={handleFileSelection} />
          </label>
        </div>
        <div className="upload-list">
          {state.uploads.length === 0 ? (
            <div className="empty-state">No uploads yet.</div>
          ) : (
            state.uploads.map((upload) => (
              <article key={upload.id} className="upload-item">
                <div>
                  <strong>{upload.name}</strong>
                  <p>{Math.round(upload.size / 1024)} KB</p>
                </div>
                <div className={`upload-status upload-status--${upload.status}`}>{upload.status}</div>
                {upload.message ? <p className="upload-message">{upload.message}</p> : null}
              </article>
            ))
          )}
        </div>
      </section>
    </section>
  );
}
