import { useState } from "react";
import { downloadMeetingReport, downloadTranscript } from "../api";

interface Props {
  meetingId: number;
}

export default function ExportButtons({ meetingId }: Props) {
  const [downloading, setDownloading] = useState("");
  const [error, setError] = useState("");

  async function runDownload(kind: "transcript" | "report") {
    setDownloading(kind);
    setError("");
    try {
      if (kind === "transcript") {
        await downloadTranscript(meetingId);
      } else {
        await downloadMeetingReport(meetingId);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Download failed.");
    } finally {
      setDownloading("");
    }
  }

  return (
    <div className="export-wrap">
      <div className="export-row">
        <button
          className="button secondary"
          type="button"
          title="Download the transcript as a Word document"
          disabled={downloading !== ""}
          onClick={() => runDownload("transcript")}
        >
          {downloading === "transcript" ? "Preparing..." : "Transcript .docx"}
        </button>
        <button
          className="button secondary"
          type="button"
          title="Download the full meeting report as a Word document"
          disabled={downloading !== ""}
          onClick={() => runDownload("report")}
        >
          {downloading === "report" ? "Preparing..." : "Full report .docx"}
        </button>
      </div>
      {error && <p className="error inline-error">{error}</p>}
    </div>
  );
}
