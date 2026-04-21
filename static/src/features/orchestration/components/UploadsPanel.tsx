import type { UploadItem } from "../types";

export function UploadsPanel({
  items,
  onUpload,
}: {
  items: UploadItem[];
  onUpload: (file: File) => Promise<void>;
}) {
  return (
    <section className="panel-card">
      <div className="panel-card__header">
        <span>Knowledge Uploads</span>
      </div>
      <label className="upload-dropzone">
        <input
          type="file"
          accept=".pdf,.docx,.txt,.md"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void onUpload(file);
            event.target.value = "";
          }}
        />
        <span>Upload PDF, DOCX, TXT, or MD</span>
      </label>
      <div className="upload-list">
        {items.length === 0 ? (
          <p className="panel-card__empty">Uploads will appear here.</p>
        ) : (
          items.map((item) => (
            <div key={item.id} className={`upload-item status-${item.status}`}>
              <div>{item.filename}</div>
              <div>{item.message ?? item.status}</div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
