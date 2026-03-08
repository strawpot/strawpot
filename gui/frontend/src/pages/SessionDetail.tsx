import { useParams } from "react-router-dom";

export default function SessionDetail() {
  const { projectId, runId } = useParams();

  return (
    <div>
      <h1>Session {runId}</h1>
      <p>Project: {projectId}</p>
      <p>Agent tree, logs, trace timeline, and artifacts will appear here.</p>
    </div>
  );
}
