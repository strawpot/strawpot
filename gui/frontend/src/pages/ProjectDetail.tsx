import { useParams } from "react-router-dom";

export default function ProjectDetail() {
  const { projectId } = useParams();

  return (
    <div>
      <h1>Project {projectId}</h1>
      <p>Sessions, Config, Files, and Registry tabs will appear here.</p>
    </div>
  );
}
